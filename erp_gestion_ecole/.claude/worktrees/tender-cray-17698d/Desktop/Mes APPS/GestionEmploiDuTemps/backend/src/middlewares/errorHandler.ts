import { Request, Response, NextFunction } from 'express';
import { logger } from '../utils/logger';

export class AppError extends Error {
  constructor(public message: string, public statusCode: number = 400) {
    super(message);
    this.name = 'AppError';
  }
}

export function errorHandler(err: Error, _req: Request, res: Response, _next: NextFunction) {
  if (err instanceof AppError) {
    return res.status(err.statusCode).json({ success: false, message: err.message });
  }
  logger.error(err.message, { stack: err.stack });
  res.status(500).json({ success: false, message: 'Erreur serveur interne' });
}
