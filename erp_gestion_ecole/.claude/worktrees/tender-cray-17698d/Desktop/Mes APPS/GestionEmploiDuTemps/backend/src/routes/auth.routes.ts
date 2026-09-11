import { Router } from 'express';
import { login, refresh, me, changePassword } from '../controllers/auth.controller';
import { authenticate } from '../middlewares/auth';

const router = Router();

/**
 * @swagger
 * /auth/login:
 *   post:
 *     summary: Connexion utilisateur
 *     tags: [Auth]
 *     security: []
 *     requestBody:
 *       required: true
 *       content:
 *         application/json:
 *           schema:
 *             type: object
 *             properties:
 *               email: { type: string }
 *               password: { type: string }
 *     responses:
 *       200:
 *         description: Connexion réussie
 */
router.post('/login', login);
router.post('/refresh', refresh);
router.get('/me', authenticate, me);
router.put('/change-password', authenticate, changePassword);

export default router;
