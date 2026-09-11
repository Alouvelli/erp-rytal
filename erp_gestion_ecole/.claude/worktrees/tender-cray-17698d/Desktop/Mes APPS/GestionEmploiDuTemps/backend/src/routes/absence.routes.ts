import { Router } from 'express';
import { getAbsences, createAbsence, justifyAbsence, validateJustification, getStudentStats } from '../controllers/absence.controller';
import { authenticate, authorize } from '../middlewares/auth';

const router = Router();
router.use(authenticate);
router.get('/', getAbsences);
router.post('/', authorize('ADMIN', 'SCOLARITE', 'TEACHER'), createAbsence);
router.put('/:id/justify', authorize('STUDENT'), justifyAbsence);
router.put('/:id/validate', authorize('ADMIN', 'SCOLARITE'), validateJustification);
router.get('/stats/:studentId', getStudentStats);
export default router;
