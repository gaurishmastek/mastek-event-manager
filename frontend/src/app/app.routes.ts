import type { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', redirectTo: 'admin', pathMatch: 'full' },
  {
    path: 'register',
    loadChildren: () => import('./public/public.routes').then((m) => m.PUBLIC_ROUTES),
  },
  {
    path: 'admin',
    loadChildren: () => import('./admin/admin.routes').then((m) => m.ADMIN_ROUTES),
  },
  {
    path: 'gate',
    loadChildren: () => import('./gate/gate.routes').then((m) => m.GATE_ROUTES),
  },
  { path: '**', redirectTo: 'admin' },
];
