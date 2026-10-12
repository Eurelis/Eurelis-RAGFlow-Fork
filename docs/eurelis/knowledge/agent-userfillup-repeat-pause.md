---
title: "Agents canvas : pause UserFillUp à chaque passage (boucles de validation)"
type: knowledge
status: reference
date: 2026-10-12
---

# Agents canvas : pause UserFillUp à chaque passage (boucles de validation)

Depuis `v0.26.3-eurelis.14` (AILAB-43, agent CRM v1.2), un composant `UserFillUp` atteint
**plusieurs fois dans la même session** refait une pause à chaque passage. Jusqu'à
`v0.26.3-eurelis.13`, seul le premier passage faisait une pause : les suivants étaient sautés et
une boucle de validation tournait sans fin.

> **En bref.** Le moteur vide désormais le formulaire d'un `UserFillUp` avant de décider s'il doit
> faire une pause. Un flux linéaire, où chaque `UserFillUp` n'est atteint qu'une fois, garde
> exactement le même comportement.

---

## 1. Le motif concerné

L'agent CRM v1.2 propose plusieurs tours de modification à chaque étape :

```
Agent:X → VariableAssigner:VersionX (env.v_x = Agent:X@content)
        → UserFillUp:ValidX {decision: Valider|Modifier (obligatoire), retour: paragraph (facultatif)}
        → VariableAssigner:DemandeX (env.d_x = UserFillUp:ValidX@retour)
        → Switch:DecisionX (decision = "Valider" → étape suivante ; sinon → Agent:X)
```

Quand l'utilisateur répond « Modifier », le flux revient sur `Agent:X`, puis repasse par le
**même** `UserFillUp:ValidX`.

## 2. Symptôme jusqu'à eurelis.13

Au 2e passage sur `UserFillUp:ValidX`, aucune pause n'a lieu :

1. le `Switch` relit `decision = Modifier`, laissé par le tour précédent ;
2. il renvoie vers `Agent:X`, qui régénère une proposition ;
3. le flux repasse sur le `UserFillUp`, toujours sans pause, et ainsi de suite.

Le flux SSE ne se termine jamais et chaque tour consomme des tokens LLM.

Le bug ne se déclenche que si **tous** les champs du formulaire ont reçu une valeur au tour
précédent. Un champ facultatif laissé à `None` compte comme « non satisfait » et force la pause.
C'est le cas courant de « Modifier » : l'utilisateur remplit `retour` pour décrire la modification.

## 3. Cause

`agent/canvas.py`, `Canvas._run_impl`, bloc de détection de pause exécuté après chaque lot de
composants :

```python
for c in path:
    o = self.get_component_obj(c)
    if o.component_name.lower() == "userfillup":
        o.invoke()
        another_inputs.update({k: v for k, v in o.get_input_elements().items()
                               if not self._is_input_field_satisfied(v)})
...
if not another_inputs:
    continue   # → pas de pause
```

La pause n'a lieu que si au moins un champ n'est pas satisfait. Or les `inputs` du `UserFillUp`
contiennent encore les valeurs saisies au passage précédent : elles sont persistées dans le DSL de
la session. Au début d'un tour, seuls les composants du `path` sont remis à zéro, et seulement
leurs **sorties** (`reset(True)`). Les entrées ne sont jamais vidées.

## 4. Correctif

Une ligne, dans ce bloc uniquement :

```python
if o.component_name.lower() == "userfillup":
    o.reset()  # Eurelis — AILAB-43 : formulaire vidé, sinon les valeurs du tour précédent font sauter la pause au 2e passage
    o.invoke()
```

`ComponentBase.reset()` sans argument vide les sorties **et** les entrées
(`agent/component/base.py`). `invoke()` recalcule ensuite les `tips`. Les champs sont donc
« non satisfaits » et la pause est émise (`user_inputs`) avec tous les champs du formulaire.

## 5. Portée vérifiée

| Point | Constat |
|---|---|
| `UserFillUp` auquel l'utilisateur vient de répondre | Non concerné. À la reprise, il est en `path[0]` et tourne dans le **premier lot** avec les valeurs reçues (`inputs` de la requête). Le bloc de pause n'examine que `path[idx:]` **après** l'exécution du lot : il ne voit que les `UserFillUp` atteints ensuite. |
| Flux linéaire (chaque `UserFillUp` atteint une fois) | Comportement identique. Au premier passage, les entrées sont déjà vides (`None`), donc le reset ne change rien. Couvert par `test_linear_flow_unchanged`. |
| Valeur d'entrée par défaut dans le DSL | Aucun cas légitime. Le dialogue de paramètres du front (`web/src/pages/agent/form/begin-form/parameter-dialog.tsx`, partagé avec `UserFillUp`) ne produit que `type`, `key`, `name`, `optional` et `options`, sans champ `value`. `agent/component/fillup.py` ne lit aucune valeur par défaut : ses sorties viennent uniquement des entrées reçues. Un `value` écrit à la main dans le DSL n'alimenterait donc jamais les sorties. Le reset n'est pas restreint aux `UserFillUp` déjà présents dans l'historique d'exécution. |
| Pré-remplissage depuis `sys.query` (premier `UserFillUp`, un seul champ) | Inchangé : le pré-remplissage a lieu dans `invoke()`, appelé après le reset. |

## 6. Tests

| Test | Type | Ce qu'il vérifie |
|---|---|---|
| `test/eurelis/unit/test_userfillup_repeat_pause.py` | Unitaire, sans stack, moteur `Canvas.run` réel | Cycle départ → Modifier → Modifier → Valider. Formulaire pré-rempli atteint par le bloc de pause. Flux linéaire inchangé. |
| `test/eurelis/eurelis_fixes/test_userfillup_repeat_pause_e2e.py` | E2E `p0`, API agents en SSE | Même cycle via les sessions et `/agents/chat/completions`. À chaque pause, il contrôle le `path[0]` persisté, une seule régénération de `Message:Version` et un nombre borné de `node_finished`. |

Canvas de test sans LLM : `test/eurelis/fixtures/agent_userfillup_loop_canvas.json`.

Les deux tests sont **rouges** sans le correctif. Le flux SSE est borné (12 `node_finished`,
timeout de lecture de 30 s) : la version boguée échoue en une dizaine de secondes au lieu de
bloquer la suite.
