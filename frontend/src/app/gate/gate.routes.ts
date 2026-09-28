import type { Routes } from '@angular/router';
import { requireRole } from '../core/auth.guard';

export const GATE_ROUTES: Routes = [
  { path: '', redirectTo: 'events', pathMatch: 'full' },
  {
    path: 'login',
    loadComponent: () => import('./officer-login.component').then((m) => m.OfficerLoginComponent),
  },
  {
    path: 'events',
    canMatch: [requireRole('security_officer', 'admin')],
    loadComponent: () => import('./assigned-events.component').then((m) => m.AssignedEventsComponent),
  },
  {
    path: 'scan/:eventId',
    canMatch: [requireRole('security_officer', 'admin')],
    loadComponent: () => import('./scanner.component').then((m) => m.ScannerComponent),
  },
];
