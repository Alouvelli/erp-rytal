import { useEffect, useState } from 'react';
import { attendanceApi } from '../services/api';
import { AttendanceSheet } from '../types';
import { useAuth } from '../context/AuthContext';
import { CheckCircleIcon, XCircleIcon, ClockIcon } from '@heroicons/react/24/outline';
import toast from 'react-hot-toast';

const STATUS_BADGE: Record<string, string> = {
  PENDING: 'badge-yellow', SIGNED: 'badge-blue', APPROVED: 'badge-green', REJECTED: 'badge-red',
};
const STATUS_LABEL: Record<string, string> = {
  PENDING: 'En attente', SIGNED: 'Signé', APPROVED: 'Validé', REJECTED: 'Rejeté',
};

export default function AttendancePage() {
  const { user } = useAuth();
  const [sheets, setSheets] = useState<AttendanceSheet[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');

  const load = () => attendanceApi.getAll(filter ? { status: filter } : {}).then(({ data }) => setSheets(data.data)).finally(() => setLoading(false));

  useEffect(() => { load(); }, [filter]);

  const sign = async (id: string) => {
    await attendanceApi.sign(id);
    toast.success('Émargement signé !');
    load();
  };

  const validate = async (id: string, status: string) => {
    await attendanceApi.validate(id, { status });
    toast.success(`Émargement ${status === 'APPROVED' ? 'validé' : 'rejeté'}`);
    load();
  };

  const canValidate = user?.role === 'ADMIN' || user?.role === 'SCOLARITE';
  const isTeacher = user?.role === 'TEACHER';

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Émargements</h1>
        <p className="text-sm text-gray-500 mt-1">Gestion des présences enseignants</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: 'En attente', count: sheets.filter(s => s.status === 'PENDING').length, color: 'text-yellow-600', bg: 'bg-yellow-50 dark:bg-yellow-900/10' },
          { label: 'Signés', count: sheets.filter(s => s.status === 'SIGNED').length, color: 'text-blue-600', bg: 'bg-blue-50 dark:bg-blue-900/10' },
          { label: 'Validés', count: sheets.filter(s => s.status === 'APPROVED').length, color: 'text-green-600', bg: 'bg-green-50 dark:bg-green-900/10' },
          { label: 'Rejetés', count: sheets.filter(s => s.status === 'REJECTED').length, color: 'text-red-600', bg: 'bg-red-50 dark:bg-red-900/10' },
        ].map(c => (
          <div key={c.label} className={`card p-4 ${c.bg}`}>
            <p className={`text-2xl font-bold ${c.color}`}>{c.count}</p>
            <p className="text-sm text-gray-600 dark:text-gray-400">{c.label}</p>
          </div>
        ))}
      </div>

      {/* Filter */}
      <div className="card p-4">
        <select className="input w-auto" value={filter} onChange={e => setFilter(e.target.value)}>
          <option value="">Tous les statuts</option>
          <option value="PENDING">En attente</option>
          <option value="SIGNED">Signés</option>
          <option value="APPROVED">Validés</option>
          <option value="REJECTED">Rejetés</option>
        </select>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-800">
              <tr>
                {['Date', 'Enseignant', 'Matière', 'Classe', 'Statut', 'Actions'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 dark:text-gray-400 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-gray-800/50">
              {loading ? (
                <tr><td colSpan={6} className="text-center py-12 text-gray-400">Chargement...</td></tr>
              ) : sheets.length === 0 ? (
                <tr><td colSpan={6} className="text-center py-12 text-gray-400">Aucun émargement trouvé</td></tr>
              ) : sheets.map(s => (
                <tr key={s.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30 transition-colors">
                  <td className="px-4 py-3 whitespace-nowrap">
                    {new Date(s.sessionDate).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' })}
                  </td>
                  <td className="px-4 py-3">{s.teacher.user.firstName} {s.teacher.user.lastName}</td>
                  <td className="px-4 py-3">{s.timetableSlot?.subject?.name ?? '-'}</td>
                  <td className="px-4 py-3">{s.timetableSlot?.class?.name ?? '-'}</td>
                  <td className="px-4 py-3">
                    <span className={`badge ${STATUS_BADGE[s.status]}`}>{STATUS_LABEL[s.status]}</span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {isTeacher && s.status === 'PENDING' && (
                        <button onClick={() => sign(s.id)} className="btn-primary py-1 px-2 text-xs">
                          <CheckCircleIcon className="w-3.5 h-3.5" /> Émarger
                        </button>
                      )}
                      {canValidate && s.status === 'SIGNED' && (
                        <>
                          <button onClick={() => validate(s.id, 'APPROVED')} className="p-1.5 text-green-600 hover:bg-green-50 rounded-lg">
                            <CheckCircleIcon className="w-4 h-4" />
                          </button>
                          <button onClick={() => validate(s.id, 'REJECTED')} className="p-1.5 text-red-600 hover:bg-red-50 rounded-lg">
                            <XCircleIcon className="w-4 h-4" />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
