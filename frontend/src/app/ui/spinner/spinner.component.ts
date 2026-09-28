import { Component } from '@angular/core';

@Component({
  selector: 'app-spinner',
  standalone: true,
  template: `
    <div class="flex justify-center py-8" role="status" aria-label="Loading">
      <span class="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary"></span>
    </div>
  `,
})
export class SpinnerComponent {}
