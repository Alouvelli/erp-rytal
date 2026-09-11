import axios from 'axios';

export const api = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('accessToken');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config;
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true;
      const refreshToken = localStorage.getItem('refreshToken');
      if (refreshToken) {
        try {
          const { data } = await axios.post('/api/v1/auth/refresh', { refreshToken });
          localStorage.setItem('accessToken', data.data.accessToken);
          original.headers.Authorization = `Bearer ${data.data.accessToken}`;
          return api(original);
        } catch {
          localStorage.clear();
          window.location.href = '/login';
        }
      }
    }
    return Promise.reject(error);
  }
);

export const authApi = {
  login: (email: string, password: string) => api.post('/auth/login', { email, password }),
  me: () => api.get('/auth/me'),
  changePassword: (data: object) => api.put('/auth/change-password', data),
};

export const timetableApi = {
  getAll: (params?: object) => api.get('/timetables', { params }),
  create: (data: object) => api.post('/timetables', data),
  update: (id: string, data: object) => api.put(`/timetables/${id}`, data),
  delete: (id: string) => api.delete(`/timetables/${id}`),
};

export const attendanceApi = {
  getAll: (params?: object) => api.get('/attendance', { params }),
  sign: (id: string) => api.put(`/attendance/${id}/sign`),
  validate: (id: string, data: object) => api.put(`/attendance/${id}/validate`, data),
  getStats: (teacherId: string) => api.get(`/attendance/stats/${teacherId}`),
};

export const gradeApi = {
  getEvaluations: (params?: object) => api.get('/grades/evaluations', { params }),
  createEvaluation: (data: object) => api.post('/grades/evaluations', data),
  saveGrades: (data: object) => api.post('/grades/save', data),
  publish: (evalId: string) => api.put(`/grades/evaluations/${evalId}/publish`),
  getStudentGrades: (studentId: string, params?: object) => api.get(`/grades/student/${studentId}`, { params }),
};

export const absenceApi = {
  getAll: (params?: object) => api.get('/absences', { params }),
  create: (data: object) => api.post('/absences', data),
  justify: (id: string, data: object) => api.put(`/absences/${id}/justify`, data),
  validate: (id: string, data: object) => api.put(`/absences/${id}/validate`, data),
  getStats: (studentId: string) => api.get(`/absences/stats/${studentId}`),
};

export const cancellationApi = {
  getAll: (params?: object) => api.get('/cancellations', { params }),
  request: (data: object) => api.post('/cancellations', data),
  validate: (id: string, data: object) => api.put(`/cancellations/${id}/validate`, data),
};

export const notificationApi = {
  getAll: () => api.get('/notifications'),
  markRead: (id: string) => api.put(`/notifications/${id}/read`),
  markAllRead: () => api.put('/notifications/read-all'),
};

export const dashboardApi = { get: () => api.get('/dashboard') };
export const classApi = {
  getAll: () => api.get('/classes'),
  create: (d: object) => api.post('/classes', d),
  update: (id: string, d: object) => api.put(`/classes/${id}`, d),
  delete: (id: string) => api.delete(`/classes/${id}`),
};
export const subjectApi = {
  getAll: () => api.get('/subjects'),
  create: (d: object) => api.post('/subjects', d),
  update: (id: string, d: object) => api.put(`/subjects/${id}`, d),
  delete: (id: string) => api.delete(`/subjects/${id}`),
};
export const roomApi = {
  getAll: () => api.get('/rooms'),
  create: (d: object) => api.post('/rooms', d),
  update: (id: string, d: object) => api.put(`/rooms/${id}`, d),
  delete: (id: string) => api.delete(`/rooms/${id}`),
};
export const teacherApi = {
  getAll: () => api.get('/users').then(r => ({ data: { data: r.data.data.filter((u: any) => u.role === 'TEACHER') } })),
};
export const userApi = {
  getAll: () => api.get('/users'),
  create: (d: object) => api.post('/users', d),
  update: (id: string, d: object) => api.put(`/users/${id}`, d),
  delete: (id: string) => api.delete(`/users/${id}`),
};
