import { Component, input } from '@angular/core';

export type ButtonVariant = 'primary' | 'secondary' | 'outline' | 'ghost' | 'destructive';

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: 'bg-primary text-primary-foreground hover:opacity-90',
  secondary: 'bg-secondary text-secondary-foreground hover:opacity-90',
  outline: 'border border-input bg-background hover:bg-accent hover:text-accent-foreground',
  ghost: 'hover:bg-accent hover:text-accent-foreground',
  destructive: 'bg-destructive text-destructive-foreground hover:opacity-90',
};

/** A spartan/ui-style button. Swap for `<hlm-button>` once `@spartan-ng/ui-button` is installed. */
@Component({
  selector: 'app-button',
  standalone: true,
  template: `
    <button
      [type]="type()"
      [disabled]="disabled() || loading()"
      [class]="
        'inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-medium ' +
        'transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none ' +
        'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ' +
        variantClass()
      "
    >
      @if (loading()) {
        <span class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></span>
      }
      <ng-content />
    </button>
  `,
})
export class ButtonComponent {
  readonly variant = input<ButtonVariant>('primary');
  readonly type = input<'button' | 'submit'>('button');
  readonly disabled = input(false);
  readonly loading = input(false);

  protected variantClass(): string {
    return VARIANT_CLASSES[this.variant()];
  }
}
