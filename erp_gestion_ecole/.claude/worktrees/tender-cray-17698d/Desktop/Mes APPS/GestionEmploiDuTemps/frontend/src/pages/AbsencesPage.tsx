import { useEffect, useState } from 'react';
import { absenceApi, timetableApi, classApi } from '../services/api';
import { StudentAbsence, Class } from '../types';
import { useAuth } from '../context/AuthContext';
import { PlusIcon, CheckCircleIcon, XCircleIcon } from '@heroicons/react/24/outline';
import { useForm } from 'react-hook-form';
import toast from 'react-hot-toast';

const STATUS_BADGE: Record<string, string> = {
  UNJUSTIFIED: 'badge-red', PENDING: 'badge-yellow', JUSTIFIED: 'badge-green',
};
const STATUS_LABEL: Record<string, string> = {
  UNJUSTIFIED: 'Non justifiée', PENDING: 'En attente', JUSTIFIED: 'Justifiée',
};

export default function AbsencesPage() {
  const { user } = useAuth();
  const [absences, setAbsences] = useState<StudentAbsence[]>([]);
  const [classes, setClasses] = useState<Class[]>([]);
  const [slots, setSlots] = useState<any[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [filterStatus, setFilterStatus] = useState('');
  const { register, handleSubmit, reset } = useForm();

  const isStudent = user?.role === 'STUDENT';
  const canCreate = user?.role === 'TEACHER' || user?.role === 'ADMIN' || user?.role === 'SCOLARITE';
  const canValidate = user?.role === 'ADMIN' || user?.role === 'SCOLARITE';

  const load = () => absenceApi.getAll(filterStatus ? { status: filterStatus } : {}).then(({ data }) => setAbsences(data.data));

  useEffect(() => {
    load();
    classApi.getAll().then(({ data }) => setClasses(data.data));
    timetableApi.getAll().then(({ data }) => setSlots(data.data));
  }, [filterStatus]);

  const create = async (data: any) => {
    try {
      await absenceApi.create({ ...data, sessionDate: new Date(data.sessionDate).toISOString() });
      toast.success('Absence enregistrée');
      setShowModal(false); reset(); load();
    } catch { toast.error('Erreur'); }
  };

  const validate = async (id: string, status: string) => {
    await absenceApi.validate(id, { status });
    toast.success('Mise à jour effectuée');
    load();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Absences</h1>
          <p className="text-sm text-gray-500 mt-1">Suivi des absences étudiants</p>
        </div>
        {canCreate && (
          <button onClick={() => setShowModal(true)} className="btn-primary">
            <PlusIcon className="w-4 h-4" /> Saisir une absence
          </button>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Non justifiées', count: absences.filter(a => a.status === 'UNJUSTIFIED').length, cls: 'text-red-600 bg-red-50 dark:bg-red-900/10' },
          { label: 'En attente', count: absences.filter(a => a.status === 'PENDING').length, cls: 'text-yellow-600 bg-yellow-50 dark:bg-yellow-900/10' },
          { label: 'Justifiées', count: absences.filter(a => a.status === 'JUSTIFIED').length, cls: 'text-green-600 bg-green-50 dark:bg-green-900/10' },
        ].map(s => (
          <div key={s.label} className={`card p-4 ${s.cls}`}>
            <p className="text-2xl font-bold">{s.count}</p>
            <p className="text-sm opacity-80">{s.label}</p>
          </div>
        ))}
      </div>

      {/* Filter */}
      <div className="card p-4">
        <select className="input w-auto" value={filterStatus} onChange={e => setFilterStatus(e.target.value)}>
          <option value="">Tous les statuts</option>
          <option value="UNJUSTIFIED">Non justifiées</option>
          <option value="PENDING">En attente de justification</option>
          <option value="JUSTIFIED">Justifiées</option>
        </select>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800/50 border-b border-gray-100 dark:border-gray-800">
              <tr>
                {['Étudiant', 'Date', 'Cours', 'Statut', 'Justification', 'Actions'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-gray-800/50">
              {absences.length === 0 ? (
                <tr><td colSpan={6} className="text-center py-12 text-gray-400">Aucune absence</td></tr>
              ) : absences.map(a => (
                <tr key={a.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                  <td className="px-4 py-3 font-medium">{a.student.user.firstName} {a.student.user.lastName}</td>
                  <td className="px-4 py-3">{new Date(a.sessionDate).toLocaleDateString('fr-FR')}</td>
                  <td className="px-4 py-3">{a.timetableSlot?.subject?.name ?? '-'}</td>
                  <td className="px-4 py-3"><span className={`badge ${STATUS_BADGE[a.status]}`}>{STATUS_LABEL[a.status]}</span></td>
                  <td className="px-4 py-3 max-w-xs truncate text-gray-500">{a.justification ?? '-'}</td>
                  <td className="px-4 py-3">
                    {canValidate && a.status === 'PENDING' && (
                      <div className="flex gap-2">
                        <button onClick={() => validate(a.id, 'JUSTIFIED')} className="p-1.5 text-green-600 hover:bg-green-50 rounded-lg">
                          <CheckCircleIcon className="w-4 h-4" />
                        </button>
                        <button onClick={() => validate(a.id, 'UNJUSTIFIED')} className="p-1.5 text-red-600 hover:bg-red-50 rounded-lg">
                          <XCircleIcon className="w-4 h-4" />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="card w-full max-w-md p-6">
            <h2 className="text-lg font-semibold mb-4">Saisir une absence</h2>
            <form onSubmit={handleSubmit(create)} className="space-y-3">
              <div>
                <label className="label">Créneau</label>
                <select className="input" {...register('timetableSlotId', { required: true })}>
                  <option value="">Choisir un créneau...</option>
                  {slots.map(s => (
                    <option key={s.id} value={s.id}>{s.subject.name} - {s.class.name} ({['Lun','Mar','Mer','Jeu','Ven','Sam'][s.dayOfWeek]} {s.startTime})</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Date de séance</label>
                <input type="date" className="input" {...register('sessionDate', { required: true })} />
              </div>
              <div>
                <label className="label">Étudiant (ID)</label>
                <input className="input" {...register('studentId', { required: true })} placeholder="ID étudiant" />
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1 justify-center">Enregistrer</button>
                <button type="button" onClick={() => { setShowModal(false); reset(); }} className="btn-secondary flex-1 justify-center">Annuler</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
