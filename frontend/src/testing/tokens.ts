/** A token shaped like the API's: header.payload.signature. The signature is fake. */
export function fakeToken(
  role: 'employee' | 'manager',
  sub = role === 'manager' ? 'm1' : 'e1',
  expiresInSeconds = 1800,
): string {
  const exp = Math.floor(Date.now() / 1000) + expiresInSeconds;
  const encode = (value: object) =>
    btoa(JSON.stringify(value)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  return `${encode({ alg: 'HS256', typ: 'JWT' })}.${encode({ sub, role, exp })}.fake-signature`;
}
