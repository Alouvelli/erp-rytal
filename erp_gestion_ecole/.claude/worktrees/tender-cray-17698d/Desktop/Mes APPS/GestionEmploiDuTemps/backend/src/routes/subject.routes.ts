import { Router, Request, Response, NextFunction } from 'express';
import { prisma } from '../utils/prisma';
import { authenticate, authorize } from '../middlewares/auth';

const router = Router();
router.use(authenticate);

router.get('/', async (_req, res, next) => {
  try {
    const subjects = await prisma.subject.findMany({ orderBy: { name: 'asc' } });
    res.json({ success: true, data: subjects });
  } catch (e) { next(e); }
});

router.post('/', authorize('ADMIN', 'SCOLARITE'), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const s = await prisma.subject.create({ data: req.body });
    res.status(201).json({ success: true, data: s });
  } catch (e) { next(e); }
});

router.put('/:id', authorize('ADMIN', 'SCOLARITE'), async (req: Request, res: Response, next: NextFunction) => {
  try {
    const s = await prisma.subject.update({ where: { id: req.params.id }, data: req.body });
    res.json({ success: true, data: s });
  } catch (e) { next(e); }
});

router.delete('/:id', authorize('ADMIN'), async (req: Request, res: Response, next: NextFunction) => {
  try {
    await prisma.subject.delete({ where: { id: req.params.id } });
    res.json({ success: true, message: 'Matière supprimée' });
  } catch (e) { next(e); }
});

export default router;
