import { Response, NextFunction } from 'express';
import { prisma } from '../utils/prisma';
import { AppError } from '../middlewares/errorHandler';
import { AuthRequest } from '../middlewares/auth';

export async function getAbsences(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { studentId, classId, from, to, status } = req.query;
    const where: any = {};
    if (studentId) where.studentId = studentId;
    if (status) where.status = status;
    if (classId) where.student = { classId };
    if (from || to) {
      where.sessionDate = {};
      if (from) where.sessionDate.gte = new Date(from as string);
      if (to) where.sessionDate.lte = new Date(to as string);
    }
    if (req.user?.role === 'STUDENT') {
      const s = await prisma.student.findUnique({ where: { userId: req.user.id } });
      if (s) where.studentId = s.id;
    }

    const absences = await prisma.studentAbsence.findMany({
      where,
      include: {
        student: { include: { user: { select: { firstName: true, lastName: true } } } },
        timetableSlot: { include: { subject: true, class: true } },
      },
      orderBy: { sessionDate: 'desc' },
    });
    res.json({ success: true, data: absences });
  } catch (e) { next(e); }
}

export async function createAbsence(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const absence = await prisma.studentAbsence.create({
      data: { ...req.body, reportedBy: req.user!.id },
      include: { student: true, timetableSlot: { include: { subject: true } } },
    });
    res.status(201).json({ success: true, data: absence });
  } catch (e) { next(e); }
}

export async function justifyAbsence(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { justification } = req.body;
    const absence = await prisma.studentAbsence.update({
      where: { id: req.params.id },
      data: { justification, status: 'PENDING' },
    });
    res.json({ success: true, data: absence });
  } catch (e) { next(e); }
}

export async function validateJustification(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { status } = req.body;
    if (!['JUSTIFIED', 'UNJUSTIFIED'].includes(status)) throw new AppError('Statut invalide', 400);
    const absence = await prisma.studentAbsence.update({
      where: { id: req.params.id },
      data: { status },
    });
    res.json({ success: true, data: absence });
  } catch (e) { next(e); }
}

export async function getStudentStats(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { studentId } = req.params;
    const [total, justified, unjustified] = await Promise.all([
      prisma.studentAbsence.count({ where: { studentId } }),
      prisma.studentAbsence.count({ where: { studentId, status: 'JUSTIFIED' } }),
      prisma.studentAbsence.count({ where: { studentId, status: 'UNJUSTIFIED' } }),
    ]);
    res.json({ success: true, data: { total, justified, unjustified, pending: total - justified - unjustified } });
  } catch (e) { next(e); }
}
