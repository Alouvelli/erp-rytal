import { Router, Response, NextFunction } from 'express';
import { prisma } from '../utils/prisma';
import { authenticate, AuthRequest } from '../middlewares/auth';

const router = Router();
router.use(authenticate);

router.get('/', async (req: AuthRequest, res: Response, next: NextFunction) => {
  try {
    const notifications = await prisma.notification.findMany({
      where: { userId: req.user!.id },
      orderBy: { createdAt: 'desc' },
      take: 50,
    });
    res.json({ success: true, data: notifications });
  } catch (e) { next(e); }
});

router.put('/:id/read', async (req: AuthRequest, res: Response, next: NextFunction) => {
  try {
    await prisma.notification.update({ where: { id: req.params.id, userId: req.user!.id }, data: { isRead: true } });
    res.json({ success: true });
  } catch (e) { next(e); }
});

router.put('/read-all', async (req: AuthRequest, res: Response, next: NextFunction) => {
  try {
    await prisma.notification.updateMany({ where: { userId: req.user!.id, isRead: false }, data: { isRead: true } });
    res.json({ success: true });
  } catch (e) { next(e); }
});

export default router;
