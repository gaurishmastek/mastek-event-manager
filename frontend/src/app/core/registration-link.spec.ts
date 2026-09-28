import { registrationLink } from './registration-link';

describe('registrationLink', () => {
  it('uses the public id under /register on the given origin', () => {
    expect(registrationLink('https://events.mastek.com', '3f2b8c1e-8a4d-4b7e-9c2a-1d2e3f4a5b6c')).toBe(
      'https://events.mastek.com/register/3f2b8c1e-8a4d-4b7e-9c2a-1d2e3f4a5b6c',
    );
  });

  it('does not double the slash after the origin', () => {
    expect(registrationLink('http://localhost:4200/', 'abc')).toBe('http://localhost:4200/register/abc');
  });
});
