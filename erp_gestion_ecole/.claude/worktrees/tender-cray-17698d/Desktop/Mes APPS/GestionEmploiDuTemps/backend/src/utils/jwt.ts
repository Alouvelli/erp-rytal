import jwt from 'jsonwebtoken';

const JWT_SECRET = process.env.JWT_SECRET!;
const JWT_REFRESH_SECRET = process.env.JWT_REFRESH_SECRET!;

export function signAccessToken(payload: object): string {
  return jwt.sign(payload, JWT_SECRET, { expiresIn: process.env.JWT_EXPIRES_IN || '15m' });
}

export function signRefreshToken(payload: object): string {
  return jwt.sign(payload, JWT_REFRESH_SECRET, { expiresIn: process.env.JWT_REFRESH_EXPIRES_IN || '7d' });
}

export function verifyAccessToken(token: string): jwt.JwtPayload {
  return jwt.verify(token, JWT_SECRET) as jwt.JwtPayload;
}

export function verifyRefreshToken(token: string): jwt.JwtPayload {
  return jwt.verify(token, JWT_REFRESH_SECRET) as jwt.JwtPayload;
}
