import { Response, NextFunction } from 'express';
import { prisma } from '../utils/prisma';
import { AppError } from '../middlewares/errorHandler';
import { AuthRequest } from '../middlewares/auth';

export async function getCancellations(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { status, teacherId } = req.query;
    const where: any = {};
    if (status) where.status = status;
    if (teacherId) where.teacherId = teacherId;
    if (req.user?.role === 'TEACHER') {
      const t = await prisma.teacher.findUnique({ where: { userId: req.user.id } });
      if (t) where.teacherId = t.id;
    }
    const list = await prisma.courseCancellation.findMany({
      where,
      include: {
        teacher: { include: { user: { select: { firstName: true, lastName: true } } } },
        timetableSlot: { include: { subject: true, class: true, room: true } },
      },
      orderBy: { createdAt: 'desc' },
    });
    res.json({ success: true, data: list });
  } catch (e) { next(e); }
}

export async function requestCancellation(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const teacher = await prisma.teacher.findUnique({ where: { userId: req.user!.id } });
    if (!teacher) throw new AppError('Enseignant introuvable', 404);

    const cancellation = await prisma.courseCancellation.create({
      data: { ...req.body, teacherId: teacher.id, status: 'PENDING' },
      include: { timetableSlot: { include: { class: { include: { students: { include: { user: { select: { id: true } } } } } } } } },
    });

    // Notify all students in the class
    const students = cancellation.timetableSlot.class.students;
    if (students.length > 0) {
      await prisma.notification.createMany({
        data: students.map((s) => ({
          userId: s.user.id,
          type: 'CANCELLATION' as const,
          title: 'Cours annulé',
          message: `Le cours du ${new Date(cancellation.sessionDate).toLocaleDateString('fr-FR')} a été signalé comme annulé. Motif: ${cancellation.reason}`,
          cancellationId: cancellation.id,
        })),
      });
    }

    res.status(201).json({ success: true, data: cancellation });
  } catch (e) { next(e); }
}

export async function validateCancellation(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { status, rescheduledDate, rescheduledRoom } = req.body;
    const cancellation = await prisma.courseCancellation.update({
      where: { id: req.params.id },
      data: { status, rescheduledDate, rescheduledRoom, validatedBy: req.user!.id, validatedAt: new Date() },
      include: {
        timetableSlot: {
          include: {
            class: { include: { students: { include: { user: { select: { id: true } } } } } },
            teacher: { include: { user: { select: { id: true } } } },
          },
        },
      },
    });

    if (status === 'APPROVED' && rescheduledDate) {
      const students = cancellation.timetableSlot.class.students;
      const teacherUserId = cancellation.timetableSlot.teacher.user.id;
      const notifyIds = [...students.map((s) => s.user.id), teacherUserId];
      await prisma.notification.createMany({
        data: notifyIds.map((uid) => ({
          userId: uid,
          type: 'RESCHEDULED' as const,
          title: 'Cours reprogrammé',
          message: `Le cours annulé a été reprogrammé au ${new Date(rescheduledDate).toLocaleDateString('fr-FR')}.`,
          cancellationId: cancellation.id,
        })),
      });
    }

    res.json({ success: true, data: cancellation });
  } catch (e) { next(e); }
}
