import { Router } from 'express';
import { getAll, create, update, remove } from '../controllers/timetable.controller';
import { authenticate, authorize } from '../middlewares/auth';

const router = Router();
router.use(authenticate);
router.get('/', getAll);
router.post('/', authorize('ADMIN', 'SCOLARITE'), create);
router.put('/:id', authorize('ADMIN', 'SCOLARITE'), update);
router.delete('/:id', authorize('ADMIN', 'SCOLARITE'), remove);
export default router;
