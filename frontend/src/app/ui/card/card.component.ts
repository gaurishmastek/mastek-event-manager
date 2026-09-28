import { Component } from '@angular/core';

/** A spartan/ui-style card shell. Swap for `<hlm-card>` once `@spartan-ng/ui-card` is installed. */
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
