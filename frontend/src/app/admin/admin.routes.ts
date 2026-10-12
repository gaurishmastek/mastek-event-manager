import type { Routes } from '@angular/router';
import { requireRole } from '../core/auth.guard';

export const ADMIN_ROUTES: Routes = [
  {
    path: 'login',
    loadComponent: () => import('./login.component').then((m) => m.AdminLoginComponent),
  },
  {
    // Full-screen request logs (the Vercel-style viewer from fastapi-logs-list), outside the admin shell.
    path: 'logs',
    canMatch: [requireRole('admin')],
    loadChildren: () => import('../logs/logs.routes').then((m) => m.LOGS_ROUTES),
  },
  {
    path: '',
    canMatch: [requireRole('admin')],
    loadComponent: () => import('./shell/admin-shell.component').then((m) => m.AdminShellComponent),
    children: [
      { path: '', redirectTo: 'events', pathMatch: 'full' },
      {
        path: 'events',
        loadComponent: () => import('./events/event-list.component').then((m) => m.EventListComponent),
      },
      {
        path: 'events/new',
        loadComponent: () => import('./events/event-form.component').then((m) => m.EventFormComponent),
      },
      {
        path: 'events/:id/registrations',
        loadComponent: () =>
          import('./events/event-registrations.component').then((m) => m.EventRegistrationsComponent),
      },
      {
        path: 'events/:id/security',
        loadComponent: () => import('./events/event-security.component').then((m) => m.EventSecurityComponent),
      },
      {
        path: 'events/:id/edit',
        loadComponent: () => import('./events/event-form.component').then((m) => m.EventFormComponent),
      },
    ],
  },
];
