import { Component } from '@angular/core';

/** A small, self-contained Tailwind card shell. */
@Component({
  selector: 'app-card',
  standalone: true,
  template: `
    <div class="rounded-lg border border-border bg-card text-card-foreground shadow-sm">
      <ng-content />
    </div>
  `,
})
export class CardComponent {}
