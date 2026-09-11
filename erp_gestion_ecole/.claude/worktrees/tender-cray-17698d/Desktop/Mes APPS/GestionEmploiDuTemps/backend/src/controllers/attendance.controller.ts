import { Response, NextFunction } from 'express';
import { prisma } from '../utils/prisma';
import { AppError } from '../middlewares/errorHandler';
import { AuthRequest } from '../middlewares/auth';

export async function getSheets(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { teacherId, status, from, to } = req.query;
    const where: any = {};
    if (teacherId) where.teacherId = teacherId;
    if (status) where.status = status;
    if (from || to) {
      where.sessionDate = {};
      if (from) where.sessionDate.gte = new Date(from as string);
      if (to) where.sessionDate.lte = new Date(to as string);
    }
    if (req.user?.role === 'TEACHER') {
      const teacher = await prisma.teacher.findUnique({ where: { userId: req.user.id } });
      if (teacher) where.teacherId = teacher.id;
    }
    const sheets = await prisma.attendanceSheet.findMany({
      where,
      include: {
        teacher: { include: { user: { select: { firstName: true, lastName: true } } } },
        timetableSlot: { include: { subject: true, class: true } },
      },
      orderBy: { sessionDate: 'desc' },
    });
    res.json({ success: true, data: sheets });
  } catch (e) { next(e); }
}

export async function signSheet(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const teacher = await prisma.teacher.findUnique({ where: { userId: req.user!.id } });
    if (!teacher) throw new AppError('Enseignant introuvable', 404);

    const sheet = await prisma.attendanceSheet.update({
      where: { id: req.params.id },
      data: { status: 'SIGNED', signedAt: new Date() },
    });
    res.json({ success: true, data: sheet });
  } catch (e) { next(e); }
}

export async function validateSheet(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { status, remarks } = req.body;
    const sheet = await prisma.attendanceSheet.update({
      where: { id: req.params.id },
      data: { status, remarks, validatedBy: req.user!.id, validatedAt: new Date() },
    });
    res.json({ success: true, data: sheet });
  } catch (e) { next(e); }
}

export async function getTeacherStats(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const teacherId = req.params.teacherId;
    const [total, done] = await Promise.all([
      prisma.timetableSlot.count({ where: { teacherId } }),
      prisma.attendanceSheet.count({ where: { teacherId, status: { in: ['SIGNED', 'APPROVED'] } } }),
    ]);
    res.json({ success: true, data: { totalSlots: total, completedSessions: done, percentage: total ? Math.round((done / total) * 100) : 0 } });
  } catch (e) { next(e); }
}
