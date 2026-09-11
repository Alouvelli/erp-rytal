import { Router } from 'express';
import { getCancellations, requestCancellation, validateCancellation } from '../controllers/cancellation.controller';
import { authenticate, authorize } from '../middlewares/auth';

const router = Router();
router.use(authenticate);
router.get('/', getCancellations);
router.post('/', authorize('TEACHER', 'ADMIN', 'SCOLARITE'), requestCancellation);
router.put('/:id/validate', authorize('ADMIN', 'SCOLARITE'), validateCancellation);
export default router;
