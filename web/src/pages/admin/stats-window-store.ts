// Eurelis — Store Zustand conservant la fenêtre temporelle du picker de stats admin.
// Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
//
// Permet de garder la sélection de date lors de la navigation entre
// /admin/stats et /admin/stats/users/<user_email>.

import { create } from 'zustand';

import {
  type TimeWindowState,
  defaultTimeWindowState,
} from '@/components/time-window-picker';

type AdminStatsWindowStore = {
  state: TimeWindowState;
  setState: (state: TimeWindowState) => void;
};

export const useAdminStatsWindowStore = create<AdminStatsWindowStore>((set) => ({
  state: defaultTimeWindowState(),
  setState: (state) => set({ state }),
}));
