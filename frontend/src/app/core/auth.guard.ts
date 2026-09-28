import { inject } from '@angular/core';
import { Router, type CanMatchFn } from '@angular/router';
import { AuthService } from './auth.service';
import type { StaffRole } from './models';

/** Requires a signed-in staff user with one of `roles`; otherwise redirects to that area's login. */
export function requireRole(...roles: StaffRole[]): CanMatchFn {
  return () => {
    const auth = inject(AuthService);
    const router = inject(Router);
    const user = auth.currentUser();
    if (user && roles.includes(user.role)) {
      return true;
    }
    const loginPath = roles.includes('security_officer') ? '/gate/login' : '/admin/login';
    return router.parseUrl(loginPath);
  };
}
