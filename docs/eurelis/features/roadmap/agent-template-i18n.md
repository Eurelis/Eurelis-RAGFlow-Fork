---
title: "Internationalisation des templates d'agent"
type: feature
status: partial
reviewed: 2026-06-28
---

# Internationalisation des templates d'agent

## Contexte

Les templates d'agent (`/agent-templates`) affichent un titre et une description localisés.
Les données sont stockées dans `agent/templates/*.json` (25 fichiers) avec les clés `en`, `zh`, `de`.

## État actuel

- **Fix appliqué** (2026-05-28, `eurelis/main`) : fallback vers `'en'` quand la langue de l'UI n'est pas supportée — les descriptions ne sont plus vides en français.
- **PR upstream soumise** : [infiniflow/ragflow#15370](https://github.com/infiniflow/ragflow/pull/15370)

## Améliorations identifiées

### 1. Système réflexif (dépend de la validation #15370)

Remplacer le type figé par un `Record<string, string>` dans `IFlowTemplate` :

```ts
// Avant
description: { en: string; zh: string; de: string };

// Après
description: Record<string, string>;
```

Et rendre la résolution de langue dynamique dans `template-card.tsx` :

```tsx
const language = useMemo(() => {
  const available = Object.keys(data.description);
  if (available.includes(i18n.language)) return i18n.language;
  const prefix = i18n.language.split('-')[0];
  if (available.includes(prefix)) return prefix;
  return available.includes('en') ? 'en' : available[0];
}, [data.description]);
```

**Avantage** : ajouter `"fr"` dans un JSON template suffit, sans aucune modif frontend.

**Condition** : attendre le retour sur #15370 avant de soumettre en PR upstream. Si la PR est refusée (les mainteneurs préfèrent les clés explicites), ne pas implémenter côté Eurelis.

### 2. Traductions françaises des templates (25 fichiers)

Une fois le système réflexif en place, ajouter `"fr": "..."` dans chaque JSON de `agent/templates/`.
Peut être automatisé via un script LLM (à définir).

## Décision en attente

- [ ] Validation de PR #15370 par l'upstream
- [ ] Choix : implémenter `Record<string, string>` localement même si l'upstream refuse ?
- [ ] Traductions FR des 25 templates
