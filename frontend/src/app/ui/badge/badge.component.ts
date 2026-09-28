import { Component, input } from '@angular/core';

export type BadgeTone = 'neutral' | 'success' | 'destructive' | 'warning';

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: 'bg-secondary text-secondary-foreground',
  success: 'bg-success text-success-foreground',
  destructive: 'bg-destructive text-destructive-foreground',
  warning: 'bg-amber-100 text-amber-900',
};

/** A spartan/ui-style badge. Swap for `<hlm-badge>` once `@spartan-ng/ui-badge` is installed. */
@Component({
  selector: 'app-badge',
  standalone: true,
  template: `
    <span [class]="'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ' + toneClass()">
      <ng-content />
    </span>
  `,
})
export class BadgeComponent {
  readonly tone = input<BadgeTone>('neutral');

  protected toneClass(): string {
    return TONE_CLASSES[this.tone()];
  }
}
