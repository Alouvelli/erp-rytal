import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import compression from 'compression';
import morgan from 'morgan';
import swaggerUi from 'swagger-ui-express';
import { swaggerSpec } from './utils/swagger';
import { errorHandler } from './middlewares/errorHandler';
import { rateLimiter } from './middlewares/rateLimiter';
import { logger } from './utils/logger';

import authRoutes from './routes/auth.routes';
import userRoutes from './routes/user.routes';
import classRoutes from './routes/class.routes';
import subjectRoutes from './routes/subject.routes';
import roomRoutes from './routes/room.routes';
import timetableRoutes from './routes/timetable.routes';
import attendanceRoutes from './routes/attendance.routes';
import gradeRoutes from './routes/grade.routes';
import absenceRoutes from './routes/absence.routes';
import cancellationRoutes from './routes/cancellation.routes';
import notificationRoutes from './routes/notification.routes';
import dashboardRoutes from './routes/dashboard.routes';

const app = express();
const PORT = process.env.PORT || 4000;

app.use(helmet());
app.use(cors({ origin: process.env.CORS_ORIGIN, credentials: true }));
app.use(compression());
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));
app.use(morgan('combined', { stream: { write: (msg) => logger.info(msg.trim()) } }));
app.use('/api', rateLimiter);

app.use('/docs', swaggerUi.serve, swaggerUi.setup(swaggerSpec, {
  customCss: '.swagger-ui .topbar { display: none }',
  customSiteTitle: 'GestionEDT API',
}));

const API = '/api/v1';
app.use(`${API}/auth`, authRoutes);
app.use(`${API}/users`, userRoutes);
app.use(`${API}/classes`, classRoutes);
app.use(`${API}/subjects`, subjectRoutes);
app.use(`${API}/rooms`, roomRoutes);
app.use(`${API}/timetables`, timetableRoutes);
app.use(`${API}/attendance`, attendanceRoutes);
app.use(`${API}/grades`, gradeRoutes);
app.use(`${API}/absences`, absenceRoutes);
app.use(`${API}/cancellations`, cancellationRoutes);
app.use(`${API}/notifications`, notificationRoutes);
app.use(`${API}/dashboard`, dashboardRoutes);

app.get('/health', (_req, res) => res.json({ status: 'OK', timestamp: new Date() }));

app.use(errorHandler);

app.listen(PORT, () => {
  logger.info(`Server running on http://localhost:${PORT}`);
  logger.info(`Swagger docs at http://localhost:${PORT}/docs`);
});

export default app;
