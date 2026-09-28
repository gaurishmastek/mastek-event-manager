import type { Routes } from '@angular/router';
import { requireRole } from '../core/auth.guard';

export const GATE_ROUTES: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./officer-login.component').then((m) => m.OfficerLoginComponent),
  },
  {
    path: 'scan/:eventId',
    canMatch: [requireRole('security_officer', 'admin')],
    loadComponent: () => import('./scanner.component').then((m) => m.ScannerComponent),
  },
];
