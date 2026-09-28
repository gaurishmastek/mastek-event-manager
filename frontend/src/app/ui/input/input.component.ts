import { Component, forwardRef, input } from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';

/** A spartan/ui-style text input with `ControlValueAccessor` for reactive forms. */
@Component({
  selector: 'app-input',
  standalone: true,
  template: `
    <input
      [type]="type()"
      [placeholder]="placeholder()"
      [value]="value"
      [disabled]="disabled"
      [attr.inputmode]="inputmode() || null"
      [attr.maxlength]="maxlength() || null"
      (input)="onInput($event)"
      (blur)="onTouched()"
      class="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm
        placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2
        focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
    />
  `,
  providers: [
    {
      provide: NG_VALUE_ACCESSOR,
      useExisting: forwardRef(() => InputComponent),
      multi: true,
    },
  ],
})
export class InputComponent implements ControlValueAccessor {
  readonly type = input<'text' | 'tel' | 'email' | 'password' | 'number'>('text');
  readonly placeholder = input('');
  readonly inputmode = input<string | undefined>(undefined);
  readonly maxlength = input<number | undefined>(undefined);

  value = '';
  disabled = false;

  private onChange: (value: string) => void = () => {};
  onTouched: () => void = () => {};

  writeValue(value: string): void {
    this.value = value ?? '';
  }

  registerOnChange(fn: (value: string) => void): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }

  setDisabledState(isDisabled: boolean): void {
    this.disabled = isDisabled;
  }

  onInput(event: Event): void {
    this.value = (event.target as HTMLInputElement).value;
    this.onChange(this.value);
  }
}
