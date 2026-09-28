import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { environment } from '../../environments/environment';
import type { SecurityOfficerCreate, StaffRole, StaffUser } from './models';

/** `backend/app/modules/users/router.py` — admin only; the backend enforces it. */
@Injectable({ providedIn: 'root' })
export class UsersApiService {
  private readonly http = inject(HttpClient);
  private readonly base = `${environment.apiBaseUrl}/users`;

  list(role?: StaffRole) {
    const params = role ? new HttpParams().set('role', role) : undefined;
    return this.http.get<StaffUser[]>(this.base, { params });
  }

  createSecurityOfficer(payload: Omit<SecurityOfficerCreate, 'role'>) {
    const body: SecurityOfficerCreate = { ...payload, role: 'security_officer' };
    return this.http.post<StaffUser>(this.base, body);
  }
}
