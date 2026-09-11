import { Response, NextFunction } from 'express';
import { prisma } from '../utils/prisma';
import { AppError } from '../middlewares/errorHandler';
import { AuthRequest } from '../middlewares/auth';

const SLOT_INCLUDE = {
  class: true,
  teacher: { include: { user: { select: { firstName: true, lastName: true } } } },
  subject: true,
  room: true,
};

export async function getAll(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { classId, teacherId, roomId, semester, dayOfWeek } = req.query;
    const where: any = {};
    if (classId) where.classId = classId;
    if (teacherId) where.teacherId = teacherId;
    if (roomId) where.roomId = roomId;
    if (semester) where.semester = Number(semester);
    if (dayOfWeek !== undefined) where.dayOfWeek = Number(dayOfWeek);

    if (req.user?.role === 'TEACHER') {
      const teacher = await prisma.teacher.findUnique({ where: { userId: req.user.id } });
      if (teacher) where.teacherId = teacher.id;
    }
    if (req.user?.role === 'STUDENT') {
      const student = await prisma.student.findUnique({ where: { userId: req.user.id } });
      if (student?.classId) where.classId = student.classId;
    }

    const slots = await prisma.timetableSlot.findMany({ where, include: SLOT_INCLUDE, orderBy: [{ dayOfWeek: 'asc' }, { startTime: 'asc' }] });
    res.json({ success: true, data: slots });
  } catch (e) { next(e); }
}

export async function create(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { classId, teacherId, subjectId, roomId, dayOfWeek, startTime, endTime, semester, weekType } = req.body;

    // Conflict detection
    const conflicts = await prisma.timetableSlot.findMany({
      where: {
        dayOfWeek,
        semester,
        OR: [
          { teacherId, OR: [{ startTime: { lt: endTime }, endTime: { gt: startTime } }] },
          { roomId, OR: [{ startTime: { lt: endTime }, endTime: { gt: startTime } }] },
          { classId, OR: [{ startTime: { lt: endTime }, endTime: { gt: startTime } }] },
        ],
      },
    });

    if (conflicts.length > 0) {
      throw new AppError('Conflit détecté : enseignant, salle ou classe déjà occupé(e) sur ce créneau', 409);
    }

    const slot = await prisma.timetableSlot.create({
      data: { classId, teacherId, subjectId, roomId, dayOfWeek, startTime, endTime, semester, weekType },
      include: SLOT_INCLUDE,
    });
    res.status(201).json({ success: true, data: slot });
  } catch (e) { next(e); }
}

export async function update(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { id } = req.params;
    const slot = await prisma.timetableSlot.update({
      where: { id },
      data: req.body,
      include: SLOT_INCLUDE,
    });
    res.json({ success: true, data: slot });
  } catch (e) { next(e); }
}

export async function remove(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    await prisma.timetableSlot.delete({ where: { id: req.params.id } });
    res.json({ success: true, message: 'Créneau supprimé' });
  } catch (e) { next(e); }
}
