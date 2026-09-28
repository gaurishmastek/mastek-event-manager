import {
  emailError,
  employeeIdError,
  guestCountError,
  isFormValid,
  mobileError,
  personNameError,
  resizeGuestNames,
  toRegistrationPayload,
  type RegistrationFormValue,
} from './registration-form';

function form(overrides: Partial<RegistrationFormValue> = {}): RegistrationFormValue {
  return {
    employeeId: 'MT-104',
    employeeName: 'Asha Patil',
    email: 'asha@example.com',
    mobile: '98765 43210',
    guestCount: 2,
    guestNames: ['Ravi Patil', 'Meera Patil'],
    consent: true,
    ...overrides,
  };
}

describe('registration form rules', () => {
  describe('resizeGuestNames', () => {
    it('gives no fields for zero guests', () => {
      expect(resizeGuestNames(['Ravi'], 0)).toEqual([]);
    });

    it('adds empty fields and keeps names at existing indexes', () => {
      expect(resizeGuestNames(['Ravi'], 3)).toEqual(['Ravi', '', '']);
    });

    it('drops names beyond a reduced count', () => {
      expect(resizeGuestNames(['Ravi', 'Meera', 'Kiran'], 1)).toEqual(['Ravi']);
    });

    it('treats invalid counts as zero', () => {
      expect(resizeGuestNames(['Ravi'], -1)).toEqual([]);
      expect(resizeGuestNames(['Ravi'], 1.5)).toEqual([]);
    });
  });

  it('validates employee ids', () => {
    expect(employeeIdError('MT-104')).toBeNull();
    expect(employeeIdError('mt_104.a')).toBeNull();
    expect(employeeIdError('')).not.toBeNull();
    expect(employeeIdError('MT 104')).not.toBeNull();
    expect(employeeIdError('-MT')).not.toBeNull();
    expect(employeeIdError('x'.repeat(31))).not.toBeNull();
  });

  it('validates names', () => {
    expect(personNameError('Asha Patil')).toBeNull();
    expect(personNameError('A')).not.toBeNull();
    expect(personNameError('   ')).not.toBeNull();
    expect(personNameError('x'.repeat(101))).not.toBeNull();
    expect(personNameError('Asha\nPatil')).not.toBeNull();
    expect(personNameError('Asha\u0007')).not.toBeNull();
  });

  it('validates email and Indian mobile numbers', () => {
    expect(emailError('asha@example.com')).toBeNull();
    expect(emailError('asha@example')).not.toBeNull();
    expect(mobileError('+91 98765-43210')).toBeNull();
    expect(mobileError('09876543210')).toBeNull();
    expect(mobileError('5876543210')).not.toBeNull();
    expect(mobileError('+1 415 555 0100')).not.toBeNull();
  });

  it('limits the guest count by the event limit and seats left', () => {
    expect(guestCountError(2, 5, 3)).toBeNull();
    expect(guestCountError(3, 5, 3)).toContain('Only 3 seats left');
    expect(guestCountError(6, 5, 100)).toContain('at most 5');
    expect(guestCountError(-1, 5, 100)).not.toBeNull();
    expect(guestCountError(1.5, 5, 100)).not.toBeNull();
    expect(guestCountError(null, 5, 100)).not.toBeNull();
    expect(guestCountError(0, 5, 0)).toBe('This event is full.');
  });

  it('requires consent, valid fields and a name for every guest', () => {
    expect(isFormValid(form(), 5, 100)).toBeTrue();
    expect(isFormValid(form({ consent: false }), 5, 100)).toBeFalse();
    expect(isFormValid(form({ guestNames: ['Ravi Patil', ''] }), 5, 100)).toBeFalse();
    expect(isFormValid(form({ guestNames: ['Ravi Patil'] }), 5, 100)).toBeFalse();
  });

  it('builds a trimmed payload with exactly the counted guest names', () => {
    const payload = toRegistrationPayload(
      form({ employeeId: ' MT-104 ', guestCount: 1, guestNames: [' Ravi Patil ', 'Meera Patil'] }),
    );

    expect(payload).toEqual({
      employee_id: 'MT-104',
      employee_name: 'Asha Patil',
      email: 'asha@example.com',
      mobile: '98765 43210',
      number_of_guests: 1,
      guest_names: ['Ravi Patil'],
      consent: true,
    });
  });
});
