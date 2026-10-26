# Eurelis — helper : exécution de code Python DANS le conteneur RAGFlow sous test (docker exec).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import os
import shutil
import subprocess


def resolve_container() -> str | None:
    """Nom du conteneur ragflow sous test : override explicite, sinon découverte par labels compose."""
    override = os.getenv("RAGFLOW_TEST_CONTAINER")
    if override:
        return override
    if shutil.which("docker") is None:
        return None
    proc = subprocess.run(
        [
            "docker", "ps",
            "--filter", "label=com.docker.compose.project=ragflow-test",
            "--filter", "label=com.docker.compose.service=ragflow-cpu",
            "--format", "{{.Names}}",
        ],
        capture_output=True, text=True,
    )
    names = [n for n in proc.stdout.split() if n]
    return names[0] if names else None


def skip_reason() -> str | None:
    """Motif de skip si le conteneur n'est pas joignable, None sinon."""
    if shutil.which("docker") is None:
        return "docker CLI indisponible sur l'hôte de test"
    if resolve_container() is None:
        return "conteneur ragflow sous test introuvable (stack de test non lancée ?)"
    return None


def docker_py(code: str, stdin: str | None = None, timeout: int = 120) -> str:
    """Exécute un snippet Python dans le conteneur RAGFlow sous test et renvoie stdout (strip)."""
    proc = subprocess.run(
        ["docker", "exec", "-i", resolve_container(), "python", "-c", code],
        input=stdin, capture_output=True, text=True, timeout=timeout,
    )
    assert proc.returncode == 0, f"docker exec a échoué (rc={proc.returncode}) : {proc.stderr.strip()[-2000:]}"
    return proc.stdout.strip()
