import { Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import Layout from './components/layout/Layout';
import LoginPage from './pages/LoginPage';
import DashboardPage from './pages/DashboardPage';
import TimetablePage from './pages/TimetablePage';
import AttendancePage from './pages/AttendancePage';
import GradesPage from './pages/GradesPage';
import AbsencesPage from './pages/AbsencesPage';
import CancellationsPage from './pages/CancellationsPage';
import AdminPage from './pages/admin/AdminPage';
import ProfilePage from './pages/ProfilePage';

function PrivateRoute({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-950">
      <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600" />
    </div>
  );
  return user ? children : <Navigate to="/login" replace />;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<PrivateRoute><Layout /></PrivateRoute>}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="dashboard" element={<DashboardPage />} />
        <Route path="timetable" element={<TimetablePage />} />
        <Route path="attendance" element={<AttendancePage />} />
        <Route path="grades" element={<GradesPage />} />
        <Route path="absences" element={<AbsencesPage />} />
        <Route path="cancellations" element={<CancellationsPage />} />
        <Route path="admin" element={<AdminPage />} />
        <Route path="profile" element={<ProfilePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </ThemeProvider>
  );
}
