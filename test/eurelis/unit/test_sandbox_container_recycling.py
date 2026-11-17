# Eurelis — non-régression AILAB-21 : un conteneur de la sandbox de code est recréé après chaque exécution.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Jusqu'à v0.26.3-eurelis.14, `release_container` remettait le conteneur dans le pool après la seule
# suppression de /workspace/<task_id> : /tmp et les processus d'arrière-plan survivaient jusqu'à
# l'exécution suivante, qui peut venir d'un autre cabinet (VM sandbox commune aux instances Synerga).
# Depuis eurelis.15, le conteneur est détruit (`docker rm -f`) puis recréé, en tâche de fond, avant de
# revenir dans le pool.
#
# L'executor manager tourne dans son propre conteneur, hors de l'image eurelis/ragflow : ces tests
# chargent son module `core.container` depuis agent/sandbox/executor_manager et remplacent Docker
# (`async_run_command`) par un faux qui enregistre les commandes. Aucun conteneur n'est lancé.

import asyncio
import importlib
import sys
from pathlib import Path
from queue import Queue

import pytest

EXECUTOR_MANAGER = Path(__file__).resolve().parents[3] / "agent" / "sandbox" / "executor_manager"
# Paquets de premier niveau de l'executor manager : retirés de sys.modules après l'import pour ne pas
# masquer d'éventuels homonymes dans les autres tests.
_TOP_LEVEL = ("core", "models", "util", "utils")
NAME = "sandbox_python_0"


@pytest.fixture(scope="module")
def container_module():
    saved = {k: v for k, v in sys.modules.items() if k.split(".")[0] in _TOP_LEVEL}
    for key in saved:
        del sys.modules[key]
    sys.path.insert(0, str(EXECUTOR_MANAGER))
    try:
        module = importlib.import_module("core.container")
        language = importlib.import_module("models.enums").SupportLanguage.PYTHON
    finally:
        sys.path.remove(str(EXECUTOR_MANAGER))
        for key in [k for k in sys.modules if k.split(".")[0] in _TOP_LEVEL]:
            del sys.modules[key]
        sys.modules.update(saved)
    return module, language


@pytest.fixture
def pool(container_module, monkeypatch):
    module, language = container_module
    queue = Queue()
    monkeypatch.setattr(module, "_CONTAINER_QUEUES", {language: queue})
    monkeypatch.setattr(module, "_RECYCLE_TASKS", set(), raising=False)
    return module, language, queue


def _fake_docker(module, monkeypatch, fail_create=0):
    """Remplace Docker : enregistre chaque commande ; `docker run` échoue `fail_create` fois."""
    commands = []
    failures = {"left": fail_create}

    async def run(*args, **kwargs):
        commands.append(list(args))
        if args[:2] == ("docker", "run") and failures["left"]:
            failures["left"] -= 1
            return 1, "", "daemon busy"
        if args[:2] == ("docker", "inspect"):
            return 0, "true\n", ""
        return 0, "", ""

    monkeypatch.setattr(module, "async_run_command", run)
    return commands


async def _drain(module):
    # getattr : sur le code upstream (sans recyclage), le test doit échouer sur ses assertions.
    while getattr(module, "_RECYCLE_TASKS", None):
        await asyncio.gather(*list(module._RECYCLE_TASKS))


def test_released_container_is_destroyed_and_recreated(pool, monkeypatch):
    """Le conteneur rendu, pourtant en état de marche, est supprimé puis recréé avant de revenir au pool."""
    module, language, queue = pool
    commands = _fake_docker(module, monkeypatch)

    async def scenario():
        await module.release_container(NAME, language)
        await _drain(module)

    asyncio.run(scenario())

    verbs = [c[:2] for c in commands]
    assert ["docker", "rm"] in verbs, commands
    assert verbs.index(["docker", "rm"]) < verbs.index(["docker", "run"])
    assert ["docker", "rm", "-f", NAME] == commands[verbs.index(["docker", "rm"])][:4]
    run = commands[verbs.index(["docker", "run"])]
    assert run[run.index("--name") + 1] == NAME
    assert list(queue.queue) == [NAME]


def test_container_is_never_returned_as_is(pool, monkeypatch):
    """Tant que la recréation n'est pas finie, le conteneur n'est pas disponible ; l'appelant n'attend pas."""
    module, language, queue = pool
    monkeypatch.setattr(module, "container_is_running", lambda name: _true())
    calls = []

    async def scenario():
        gate = asyncio.Event()

        async def recreate(name, lang):
            calls.append(name)
            await gate.wait()
            return True

        monkeypatch.setattr(module, "recreate_container", recreate)
        await module.release_container(NAME, language)
        released_before_recreation = list(queue.queue)
        await asyncio.sleep(0)
        recreation_started = list(calls)
        gate.set()
        await _drain(module)
        return released_before_recreation, recreation_started

    before, started = asyncio.run(scenario())
    assert before == []
    assert started == [NAME]
    assert list(queue.queue) == [NAME]


def test_recycling_retries_until_docker_accepts(pool, monkeypatch):
    """Si Docker refuse la recréation, on réessaie avec un délai croissant ; le conteneur finit au pool, une fois."""
    module, language, queue = pool
    commands = _fake_docker(module, monkeypatch, fail_create=3)
    delays = []
    real_sleep = asyncio.sleep

    async def fast_sleep(delay, *args, **kwargs):
        delays.append(delay)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)

    async def scenario():
        await module.release_container(NAME, language)
        await _drain(module)

    asyncio.run(scenario())

    assert sum(1 for c in commands if c[:2] == ["docker", "rm"]) == 4
    assert delays == [1, 2, 4]
    assert list(queue.queue) == [NAME]


async def _true():
    return True
