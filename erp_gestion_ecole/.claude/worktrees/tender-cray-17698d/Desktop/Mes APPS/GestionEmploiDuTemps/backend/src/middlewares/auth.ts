import { Request, Response, NextFunction } from 'express';
import { verifyAccessToken } from '../utils/jwt';
import { AppError } from './errorHandler';
import { Role } from '@prisma/client';

export interface AuthRequest extends Request {
  user?: { id: string; role: Role; email: string };
}

export function authenticate(req: AuthRequest, _res: Response, next: NextFunction) {
  const auth = req.headers.authorization;
  if (!auth?.startsWith('Bearer ')) throw new AppError('Token manquant', 401);
  try {
    const payload = verifyAccessToken(auth.split(' ')[1]);
    req.user = { id: payload.id, role: payload.role, email: payload.email };
    next();
  } catch {
    throw new AppError('Token invalide ou expiré', 401);
  }
}

export function authorize(...roles: Role[]) {
  return (req: AuthRequest, _res: Response, next: NextFunction) => {
    if (!req.user || !roles.includes(req.user.role)) {
      throw new AppError('Accès non autorisé', 403);
    }
    next();
  };
}
