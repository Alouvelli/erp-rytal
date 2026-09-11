import { Response, NextFunction } from 'express';
import { prisma } from '../utils/prisma';
import { AuthRequest } from '../middlewares/auth';

export async function getDashboard(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const today = new Date();
    const dayOfWeek = today.getDay() === 0 ? 6 : today.getDay() - 1;
    const startOfWeek = new Date(today); startOfWeek.setDate(today.getDate() - dayOfWeek); startOfWeek.setHours(0,0,0,0);
    const endOfWeek = new Date(startOfWeek); endOfWeek.setDate(startOfWeek.getDate() + 7);

    const [
      totalStudents, totalTeachers, totalClasses,
      pendingAttendance, pendingCancellations,
      todaySlots, recentAbsences,
    ] = await Promise.all([
      prisma.student.count(),
      prisma.teacher.count(),
      prisma.class.count(),
      prisma.attendanceSheet.count({ where: { status: 'PENDING' } }),
      prisma.courseCancellation.count({ where: { status: 'PENDING' } }),
      prisma.timetableSlot.findMany({
        where: { dayOfWeek },
        include: { subject: true, teacher: { include: { user: { select: { firstName: true, lastName: true } } } }, room: true, class: true },
        orderBy: { startTime: 'asc' },
        take: 10,
      }),
      prisma.studentAbsence.count({ where: { sessionDate: { gte: startOfWeek, lt: endOfWeek } } }),
    ]);

    res.json({
      success: true,
      data: {
        stats: { totalStudents, totalTeachers, totalClasses, pendingAttendance, pendingCancellations, weeklyAbsences: recentAbsences },
        todaySlots,
      },
    });
  } catch (e) { next(e); }
}
