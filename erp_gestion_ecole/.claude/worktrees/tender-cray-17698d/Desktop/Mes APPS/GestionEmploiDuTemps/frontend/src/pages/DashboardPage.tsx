import { useEffect, useState } from 'react';
import { dashboardApi } from '../services/api';
import { DashboardStats, TimetableSlot } from '../types';
import {
  UsersIcon, AcademicCapIcon, BuildingLibraryIcon,
  ClipboardDocumentCheckIcon, XCircleIcon, UserMinusIcon,
} from '@heroicons/react/24/outline';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const DAYS = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi'];

function StatCard({ label, value, icon: Icon, color }: { label: string; value: number; icon: any; color: string }) {
  return (
    <div className="card p-6 flex items-center gap-4">
      <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${color}`}>
        <Icon className="w-6 h-6 text-white" />
      </div>
      <div>
        <p className="text-2xl font-bold text-gray-900 dark:text-white">{value}</p>
        <p className="text-sm text-gray-500">{label}</p>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [todaySlots, setTodaySlots] = useState<TimetableSlot[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    dashboardApi.get().then(({ data }) => {
      setStats(data.data.stats);
      setTodaySlots(data.data.todaySlots);
    }).finally(() => setLoading(false));
  }, []);

  const chartData = DAYS.map((day, i) => ({ day, cours: Math.floor(Math.random() * 8) + 1 }));

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
    </div>
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Tableau de bord</h1>
        <p className="text-gray-500 mt-1">Vue d'ensemble de la plateforme académique</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        <StatCard label="Étudiants" value={stats?.totalStudents ?? 0} icon={UsersIcon} color="bg-blue-500" />
        <StatCard label="Enseignants" value={stats?.totalTeachers ?? 0} icon={AcademicCapIcon} color="bg-purple-500" />
        <StatCard label="Classes" value={stats?.totalClasses ?? 0} icon={BuildingLibraryIcon} color="bg-green-500" />
        <StatCard label="Émargements en attente" value={stats?.pendingAttendance ?? 0} icon={ClipboardDocumentCheckIcon} color="bg-yellow-500" />
        <StatCard label="Annulations en attente" value={stats?.pendingCancellations ?? 0} icon={XCircleIcon} color="bg-red-500" />
        <StatCard label="Absences (semaine)" value={stats?.weeklyAbsences ?? 0} icon={UserMinusIcon} color="bg-orange-500" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Today's slots */}
        <div className="lg:col-span-2 card p-6">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-4">Cours du jour</h2>
          {todaySlots.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              <AcademicCapIcon className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p>Aucun cours aujourd'hui</p>
            </div>
          ) : (
            <div className="space-y-3">
              {todaySlots.map(slot => (
                <div key={slot.id} className="flex items-center gap-4 p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
                  <div className="text-center min-w-[64px]">
                    <p className="text-sm font-bold text-primary-600">{slot.startTime}</p>
                    <p className="text-xs text-gray-400">{slot.endTime}</p>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-sm text-gray-900 dark:text-white truncate">{slot.subject.name}</p>
                    <p className="text-xs text-gray-500 truncate">
                      {slot.teacher.user.firstName} {slot.teacher.user.lastName} • {slot.class.name} • {slot.room.name}
                    </p>
                  </div>
                  <span className="badge badge-blue shrink-0">{slot.subject.code}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Weekly chart */}
        <div className="card p-6">
          <h2 className="text-base font-semibold text-gray-900 dark:text-white mb-4">Cours par jour</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={chartData} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" className="text-gray-100 dark:text-gray-800" />
              <XAxis dataKey="day" tick={{ fontSize: 11 }} tickLine={false} />
              <YAxis tick={{ fontSize: 11 }} tickLine={false} />
              <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} />
              <Bar dataKey="cours" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
