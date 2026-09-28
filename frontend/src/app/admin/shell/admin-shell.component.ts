import { Component, inject } from '@angular/core';
import { Router, RouterLink, RouterOutlet } from '@angular/router';
import { AuthService } from '../../core/auth.service';
import { ButtonComponent } from '../../ui/button/button.component';

@Component({
  selector: 'app-admin-shell',
  standalone: true,
  imports: [RouterLink, RouterOutlet, ButtonComponent],
  templateUrl: './admin-shell.component.html',
})
export class AdminShellComponent {
  protected readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  signOut(): void {
    this.auth.logout();
    this.router.navigateByUrl('/admin/login');
  }
}
