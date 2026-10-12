import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, inject, provideZoneChangeDetection } from '@angular/core';
import { provideRouter } from '@angular/router';

import { environment } from '../environments/environment';
import { authInterceptor } from './core/auth.interceptor';
import { AuthService } from './core/auth.service';
import { LOGS_API_BASE, LOGS_EXTRA_PARAMS } from './logs/logs-api.service';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZoneChangeDetection({ eventCoalescing: true }),
    provideRouter(routes),
    provideHttpClient(withInterceptors([authInterceptor])),
    { provide: LOGS_API_BASE, useValue: `${environment.apiBaseUrl}/logs` },
    {
      // The logs page's Live stream and downloads cannot send the Authorization header, so they pass the token here.
      provide: LOGS_EXTRA_PARAMS,
      useFactory: () => {
        const auth = inject(AuthService);
        return (): Record<string, string> => {
          const token = auth.getAccessToken();
          return token ? { token } : {};
        };
      },
    },
  ],
};
