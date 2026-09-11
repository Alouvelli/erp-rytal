import { Router } from 'express';
import { getEvaluations, createEvaluation, saveGrades, publishGrades, getStudentGrades } from '../controllers/grade.controller';
import { authenticate, authorize } from '../middlewares/auth';

const router = Router();
router.use(authenticate);
router.get('/evaluations', getEvaluations);
router.post('/evaluations', authorize('ADMIN', 'SCOLARITE', 'TEACHER'), createEvaluation);
router.post('/save', authorize('ADMIN', 'SCOLARITE', 'TEACHER'), saveGrades);
router.put('/evaluations/:evaluationId/publish', authorize('ADMIN', 'SCOLARITE', 'TEACHER'), publishGrades);
router.get('/student/:studentId', getStudentGrades);
export default router;
