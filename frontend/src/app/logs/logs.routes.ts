import { Routes } from '@angular/router';

import { LogsPageComponent } from './logs-page.component';

/** Lazy-load with: { path: 'logs', loadChildren: () => import('./logs/logs.routes').then(m => m.LOGS_ROUTES) } */
export const LOGS_ROUTES: Routes = [{ path: '', component: LogsPageComponent, data: { title: 'Mastek Event Manager' } }];
