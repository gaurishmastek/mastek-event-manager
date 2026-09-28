import type { Routes } from '@angular/router';

export const PUBLIC_ROUTES: Routes = [
  {
    path: ':eventId',
    loadComponent: () => import('./registration-flow.component').then((m) => m.RegistrationFlowComponent),
  },
];
