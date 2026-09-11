import { Router } from 'express';
import { getSheets, signSheet, validateSheet, getTeacherStats } from '../controllers/attendance.controller';
import { authenticate, authorize } from '../middlewares/auth';

const router = Router();
router.use(authenticate);
router.get('/', getSheets);
router.put('/:id/sign', authorize('TEACHER'), signSheet);
router.put('/:id/validate', authorize('ADMIN', 'SCOLARITE'), validateSheet);
router.get('/stats/:teacherId', getTeacherStats);
export default router;
