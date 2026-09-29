import {
  accompanyingCount,
  clearInapplicable,
  emailError,
  employeeIdError,
  familyMembersError,
  foodPreferenceError,
  guestCountError,
  isFormValid,
  kidsError,
  mobileError,
  partyError,
  personNameError,
  toRegistrationPayload,
  type RegistrationFormValue,
} from './registration-form';

function form(overrides: Partial<RegistrationFormValue> = {}): RegistrationFormValue {
  return {
    employeeId: 'MT-104',
    employeeName: 'Asha Patil',
    email: 'asha@example.com',
    mobile: '98765 43210',
    attending: true,
    familyAttending: true,
    withAdult: true,
    withKids: true,
    adultName: 'Ravi Patil',
    kidNames: ['Meera Patil'],
    foodPreference: 'VEG',
    consent: true,
    ...overrides,
  };
}

const BASE_PAYLOAD = {
  employee_id: 'MT-104',
  employee_name: 'Asha Patil',
  email: 'asha@example.com',
  mobile: '98765 43210',
  consent: true as const,
};

describe('registration form rules', () => {
  describe('clearInapplicable', () => {
    it('clears every family and food answer when not attending', () => {
      const cleared = clearInapplicable(form({ attending: false }));

      expect(cleared).toEqual(
        form({
          attending: false,
          familyAttending: null,
          withAdult: false,
          withKids: false,
          adultName: '',
          kidNames: [],
          foodPreference: null,
        }),
      );
    });

    it('clears family members but keeps food when attending alone', () => {
      const cleared = clearInapplicable(form({ familyAttending: false }));

      expect([cleared.withAdult, cleared.withKids, cleared.adultName, cleared.kidNames]).toEqual([false, false, '', []]);
      expect(cleared.foodPreference).toBe('VEG');
    });

    it('clears the adult name when Adult is unticked and kid names when Kids is unticked', () => {
      expect(clearInapplicable(form({ withAdult: false })).adultName).toBe('');
      expect(clearInapplicable(form({ withKids: false })).kidNames).toEqual([]);
    });

    it('never keeps more than four kids', () => {
      expect(clearInapplicable(form({ kidNames: ['A1', 'A2', 'A3', 'A4', 'A5'] })).kidNames.length).toBe(4);
    });
  });

  it('counts the adult and kids as accompanying guests', () => {
    expect(accompanyingCount(form({ kidNames: ['Meera', 'Kiran'] }))).toBe(3);
    expect(accompanyingCount(form({ withAdult: false }))).toBe(1);
    expect(accompanyingCount(form({ familyAttending: false }))).toBe(0);
    expect(accompanyingCount(form({ attending: false }))).toBe(0);
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

  it('limits the party by the event limit and seats left', () => {
    expect(guestCountError(2, 5, 3)).toBeNull();
    expect(guestCountError(3, 5, 3)).toContain('Only 3 seats left');
    expect(guestCountError(6, 5, 100)).toContain('at most 5');
    expect(guestCountError(0, 5, 0)).toBe('This event is full.');
    expect(partyError(form(), 1, 100)).toContain('at most 1 guest');
    expect(partyError(form({ attending: false }), 0, 0)).toBeNull(); // declining needs no seat
  });

  it('requires Adult, Kids or both when family is coming', () => {
    expect(familyMembersError(form({ withAdult: false, withKids: false }))).toContain('Adult, Kids or both');
    expect(familyMembersError(form())).toBeNull();
    expect(familyMembersError(form({ familyAttending: false, withAdult: false, withKids: false }))).toBeNull();
  });

  it('requires one to four kids when Kids is ticked', () => {
    expect(kidsError(form({ kidNames: [] }))).toContain('at least one');
    expect(kidsError(form({ kidNames: ['A1', 'A2', 'A3', 'A4', 'A5'] }))).toContain('at most 4');
    expect(kidsError(form({ kidNames: ['A1', 'A2', 'A3', 'A4'] }))).toBeNull();
    expect(kidsError(form({ withKids: false, kidNames: [] }))).toBeNull();
  });

  it('requires a food preference from attendees only', () => {
    expect(foodPreferenceError(form({ foodPreference: null }))).not.toBeNull();
    expect(foodPreferenceError(form({ familyAttending: false, foodPreference: null }))).not.toBeNull();
    expect(foodPreferenceError(form({ attending: false, foodPreference: null }))).toBeNull();
  });

  describe('isFormValid', () => {
    it('accepts every valid combination', () => {
      expect(isFormValid(form(), 5, 100)).toBeTrue();
      expect(isFormValid(form({ withKids: false }), 5, 100)).toBeTrue(); // adult only
      expect(isFormValid(form({ withAdult: false }), 5, 100)).toBeTrue(); // kids only
      expect(isFormValid(form({ kidNames: ['A1', 'A2', 'A3', 'A4'] }), 5, 100)).toBeTrue();
      expect(isFormValid(form({ familyAttending: false }), 5, 100)).toBeTrue(); // alone
    });

    it('lets a guest who is not attending submit with nothing else answered, even hidden junk', () => {
      expect(isFormValid(form({ attending: false, adultName: '', kidNames: [''], foodPreference: null }), 0, 0)).toBeTrue();
    });

    it('rejects unanswered or incomplete required answers', () => {
      expect(isFormValid(form({ consent: false }), 5, 100)).toBeFalse();
      expect(isFormValid(form({ attending: null }), 5, 100)).toBeFalse();
      expect(isFormValid(form({ familyAttending: null }), 5, 100)).toBeFalse();
      expect(isFormValid(form({ adultName: '' }), 5, 100)).toBeFalse();
      expect(isFormValid(form({ kidNames: ['Meera Patil', ''] }), 5, 100)).toBeFalse();
      expect(isFormValid(form({ kidNames: [] }), 5, 100)).toBeFalse();
      expect(isFormValid(form({ withAdult: false, withKids: false }), 5, 100)).toBeFalse();
      expect(isFormValid(form({ foodPreference: null }), 5, 100)).toBeFalse();
      expect(isFormValid(form(), 1, 100)).toBeFalse(); // over the event's guest limit
    });
  });

  describe('toRegistrationPayload', () => {
    it('sends only the attendance answer when not attending', () => {
      expect(toRegistrationPayload(form({ attending: false }))).toEqual({ ...BASE_PAYLOAD, attending: false });
    });

    it('sends no family members when attending alone', () => {
      expect(toRegistrationPayload(form({ familyAttending: false, foodPreference: 'JAIN' }))).toEqual({
        ...BASE_PAYLOAD,
        attending: true,
        family_attending: false,
        food_preference: 'JAIN',
      });
    });

    it('sends trimmed family names, dropping the unticked adult', () => {
      const payload = toRegistrationPayload(
        form({ employeeId: ' MT-104 ', withAdult: false, kidNames: [' Meera Patil ', 'Kiran'], foodPreference: 'FAST_FOOD' }),
      );

      expect(payload).toEqual({
        ...BASE_PAYLOAD,
        attending: true,
        family_attending: true,
        accompanying_adult: false,
        adult_name: null,
        accompanying_kids: true,
        kid_names: ['Meera Patil', 'Kiran'],
        food_preference: 'FAST_FOOD',
      });
    });
  });
});
