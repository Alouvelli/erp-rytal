import { Request, Response, NextFunction } from 'express';
import bcrypt from 'bcryptjs';
import { prisma } from '../utils/prisma';
import { signAccessToken, signRefreshToken, verifyRefreshToken } from '../utils/jwt';
import { AppError } from '../middlewares/errorHandler';

export async function login(req: Request, res: Response, next: NextFunction) {
  try {
    const { email, password } = req.body;
    const user = await prisma.user.findUnique({ where: { email } });
    if (!user || !user.isActive) throw new AppError('Identifiants invalides', 401);

    const valid = await bcrypt.compare(password, user.password);
    if (!valid) throw new AppError('Identifiants invalides', 401);

    const payload = { id: user.id, role: user.role, email: user.email };
    const accessToken = signAccessToken(payload);
    const refreshToken = signRefreshToken(payload);

    res.json({
      success: true,
      data: {
        accessToken,
        refreshToken,
        user: { id: user.id, firstName: user.firstName, lastName: user.lastName, email: user.email, role: user.role, avatar: user.avatar },
      },
    });
  } catch (e) { next(e); }
}

export async function refresh(req: Request, res: Response, next: NextFunction) {
  try {
    const { refreshToken } = req.body;
    if (!refreshToken) throw new AppError('Refresh token manquant', 401);
    const payload = verifyRefreshToken(refreshToken);
    const user = await prisma.user.findUnique({ where: { id: payload.id } });
    if (!user || !user.isActive) throw new AppError('Utilisateur introuvable', 401);
    const newPayload = { id: user.id, role: user.role, email: user.email };
    res.json({ success: true, data: { accessToken: signAccessToken(newPayload) } });
  } catch (e) { next(e); }
}

export async function me(req: Request & { user?: any }, res: Response, next: NextFunction) {
  try {
    const user = await prisma.user.findUnique({
      where: { id: req.user!.id },
      select: { id: true, firstName: true, lastName: true, email: true, role: true, avatar: true, phone: true },
    });
    res.json({ success: true, data: user });
  } catch (e) { next(e); }
}

export async function changePassword(req: Request & { user?: any }, res: Response, next: NextFunction) {
  try {
    const { currentPassword, newPassword } = req.body;
    const user = await prisma.user.findUnique({ where: { id: req.user!.id } });
    if (!user) throw new AppError('Utilisateur introuvable', 404);
    const valid = await bcrypt.compare(currentPassword, user.password);
    if (!valid) throw new AppError('Mot de passe actuel incorrect', 400);
    const hashed = await bcrypt.hash(newPassword, 12);
    await prisma.user.update({ where: { id: user.id }, data: { password: hashed } });
    res.json({ success: true, message: 'Mot de passe modifié avec succès' });
  } catch (e) { next(e); }
}
