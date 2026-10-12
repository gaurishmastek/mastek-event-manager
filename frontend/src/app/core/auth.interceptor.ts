import type { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { AuthService } from './auth.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const token = auth.getAccessToken();
  if (!token) {
    return next(req);
  }
  return next(
    req.clone({
      setHeaders: { Authorization: `Bearer ${token}` },
      // The logs page adds ?token= for its Live stream and downloads, which cannot send headers. Requests made here
      // carry the header instead, so drop the copy in the URL where server and proxy access logs would record it.
      params: req.params.delete('token'),
    }),
  );
};
