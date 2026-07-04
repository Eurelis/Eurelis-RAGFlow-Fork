# Eurelis — validation de contrat de schéma (JSON Schema) avec messages d'erreur lisibles.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

from jsonschema import Draft202012Validator


def assert_valid(instance, schema: dict, label: str = "") -> None:
    """Valide `instance` contre `schema` ; lève AssertionError listant toutes les violations."""
    errors = sorted(Draft202012Validator(schema).iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        details = "\n".join(
            f"  - {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors
        )
        raise AssertionError(f"Contrat de schéma violé{(' — ' + label) if label else ''} :\n{details}")
