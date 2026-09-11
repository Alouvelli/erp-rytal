import { Router, Request, Response, NextFunction } from 'express';
import { prisma } from '../utils/prisma';
import bcrypt from 'bcryptjs';
import { authenticate, authorize, AuthRequest } from '../middlewares/auth';
import { AppError } from '../middlewares/errorHandler';

const router = Router();
router.use(authenticate);

router.get('/', authorize('ADMIN', 'SCOLARITE'), async (_req, res, next) => {
  try {
    const users = await prisma.user.findMany({ select: { id: true, firstName: true, lastName: true, email: true, role: true, isActive: true, createdAt: true } });
    res.json({ success: true, data: users });
  } catch (e) { next(e); }
});

router.post('/', authorize('ADMIN'), async (req: AuthRequest, res: Response, next: NextFunction) => {
  try {
    const { email, password, firstName, lastName, role, phone, employeeId, studentId, classId, enrolledYear, department } = req.body;
    const hashed = await bcrypt.hash(password, 12);
    const user = await prisma.user.create({ data: { email, password: hashed, firstName, lastName, role, phone } });

    if (role === 'TEACHER') {
      await prisma.teacher.create({ data: { userId: user.id, employeeId: employeeId || `T${Date.now()}`, department } });
    }
    if (role === 'STUDENT') {
      await prisma.student.create({ data: { userId: user.id, studentId: studentId || `S${Date.now()}`, classId, enrolledYear: enrolledYear || new Date().getFullYear() } });
    }

    res.status(201).json({ success: true, data: { id: user.id, email: user.email, role: user.role } });
  } catch (e) { next(e); }
});

router.put('/:id', authorize('ADMIN'), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const { password, ...rest } = req.body;
    const data: any = { ...rest };
    if (password) data.password = await bcrypt.hash(password, 12);
    const user = await prisma.user.update({ where: { id: req.params.id }, data, select: { id: true, firstName: true, lastName: true, email: true, role: true } });
    res.json({ success: true, data: user });
  } catch (e) { next(e); }
});

router.delete('/:id', authorize('ADMIN'), async (req: Request, res: Response, next: NextFunction) => {
  try {
    await prisma.user.update({ where: { id: req.params.id }, data: { isActive: false } });
    res.json({ success: true, message: 'Utilisateur désactivé' });
  } catch (e) { next(e); }
});

export default router;
