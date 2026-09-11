import { Response, NextFunction } from 'express';
import { prisma } from '../utils/prisma';
import { AppError } from '../middlewares/errorHandler';
import { AuthRequest } from '../middlewares/auth';

export async function getEvaluations(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { classId, subjectId, semester } = req.query;
    const where: any = {};
    if (classId) where.classId = classId as string;
    if (subjectId) where.subjectId = subjectId as string;
    if (semester) where.semester = Number(semester);

    const evals = await prisma.evaluation.findMany({
      where,
      include: { subject: true, grades: { include: { student: { include: { user: { select: { firstName: true, lastName: true } } } } } } },
      orderBy: { date: 'desc' },
    });
    res.json({ success: true, data: evals });
  } catch (e) { next(e); }
}

export async function createEvaluation(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const evaluation = await prisma.evaluation.create({ data: req.body, include: { subject: true } });
    res.status(201).json({ success: true, data: evaluation });
  } catch (e) { next(e); }
}

export async function saveGrades(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { evaluationId, grades } = req.body as { evaluationId: string; grades: { studentId: string; score: number | null; isAbsent?: boolean; comment?: string }[] };

    const upserts = grades.map((g) =>
      prisma.grade.upsert({
        where: { studentId_evaluationId: { studentId: g.studentId, evaluationId } },
        update: { score: g.score, isAbsent: g.isAbsent ?? false, comment: g.comment },
        create: { studentId: g.studentId, evaluationId, score: g.score, isAbsent: g.isAbsent ?? false, comment: g.comment },
      })
    );
    await prisma.$transaction(upserts);
    res.json({ success: true, message: 'Notes enregistrées' });
  } catch (e) { next(e); }
}

export async function publishGrades(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    const { evaluationId } = req.params;
    await prisma.grade.updateMany({ where: { evaluationId }, data: { publishedAt: new Date() } });

    // Notify students
    const grades = await prisma.grade.findMany({ where: { evaluationId }, select: { studentId: true, student: { select: { userId: true } } } });
    const evaluation = await prisma.evaluation.findUnique({ where: { id: evaluationId }, include: { subject: true } });

    await prisma.notification.createMany({
      data: grades.map((g) => ({
        userId: g.student.userId,
        type: 'GRADE' as const,
        title: 'Nouvelles notes publiées',
        message: `Vos notes pour ${evaluation?.subject.name} (${evaluation?.type}) ont été publiées.`,
      })),
    });

    res.json({ success: true, message: 'Notes publiées et étudiants notifiés' });
  } catch (e) { next(e); }
}

export async function getStudentGrades(req: AuthRequest, res: Response, next: NextFunction) {
  try {
    let studentId = req.params.studentId;
    if (req.user?.role === 'STUDENT') {
      const s = await prisma.student.findUnique({ where: { userId: req.user.id } });
      if (!s) throw new AppError('Étudiant introuvable', 404);
      studentId = s.id;
    }
    const { semester } = req.query;
    const grades = await prisma.grade.findMany({
      where: { studentId, evaluation: semester ? { semester: Number(semester) } : {} },
      include: { evaluation: { include: { subject: true } } },
    });

    // Group by subject and compute averages
    const bySubject = new Map<string, { subject: any; grades: typeof grades; average: number }>();
    for (const g of grades) {
      const key = g.evaluation.subjectId;
      if (!bySubject.has(key)) bySubject.set(key, { subject: g.evaluation.subject, grades: [], average: 0 });
      bySubject.get(key)!.grades.push(g);
    }
    for (const [, v] of bySubject) {
      const scored = v.grades.filter((g) => g.score !== null && !g.isAbsent);
      const totalW = scored.reduce((s, g) => s + g.evaluation.weight, 0);
      v.average = totalW ? scored.reduce((s, g) => s + (g.score! / g.evaluation.maxScore) * 20 * g.evaluation.weight, 0) / totalW : 0;
    }

    res.json({ success: true, data: { grades, bySubject: Object.fromEntries(bySubject) } });
  } catch (e) { next(e); }
}
