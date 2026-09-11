import { useEffect, useState } from 'react';
import { cancellationApi, timetableApi } from '../services/api';
import { CourseCancellation } from '../types';
import { useAuth } from '../context/AuthContext';
import { PlusIcon, CheckCircleIcon, XCircleIcon } from '@heroicons/react/24/outline';
import { useForm } from 'react-hook-form';
import toast from 'react-hot-toast';

const STATUS_BADGE: Record<string, string> = { PENDING: 'badge-yellow', APPROVED: 'badge-green', REJECTED: 'badge-red' };
const STATUS_LABEL: Record<string, string> = { PENDING: 'En attente', APPROVED: 'Approuvée', REJECTED: 'Rejetée' };

export default function CancellationsPage() {
  const { user } = useAuth();
  const [items, setItems] = useState<CourseCancellation[]>([]);
  const [slots, setSlots] = useState<any[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [showValidateModal, setShowValidateModal] = useState<string | null>(null);
  const { register, handleSubmit, reset } = useForm();
  const { register: regV, handleSubmit: handleV, reset: resetV } = useForm();

  const canCreate = user?.role === 'TEACHER' || user?.role === 'ADMIN';
  const canValidate = user?.role === 'ADMIN' || user?.role === 'SCOLARITE';

  const load = () => cancellationApi.getAll().then(({ data }) => setItems(data.data));

  useEffect(() => {
    load();
    timetableApi.getAll().then(({ data }) => setSlots(data.data));
  }, []);

  const request = async (data: any) => {
    try {
      await cancellationApi.request({ ...data, sessionDate: new Date(data.sessionDate).toISOString() });
      toast.success('Demande envoyée et étudiants notifiés');
      setShowModal(false); reset(); load();
    } catch { toast.error('Erreur'); }
  };

  const validate = async (data: any) => {
    if (!showValidateModal) return;
    try {
      await cancellationApi.validate(showValidateModal, {
        status: data.status,
        rescheduledDate: data.rescheduledDate ? new Date(data.rescheduledDate).toISOString() : undefined,
        rescheduledRoom: data.rescheduledRoom,
      });
      toast.success('Décision enregistrée');
      setShowValidateModal(null); resetV(); load();
    } catch { toast.error('Erreur'); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Annulations de cours</h1>
          <p className="text-sm text-gray-500 mt-1">Gestion des cours annulés et reports</p>
        </div>
        {canCreate && (
          <button onClick={() => setShowModal(true)} className="btn-primary">
            <PlusIcon className="w-4 h-4" /> Demander une annulation
          </button>
        )}
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 dark:bg-gray-800/50 border-b">
              <tr>
                {['Date', 'Enseignant', 'Cours', 'Motif', 'Statut', 'Report', 'Actions'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50 dark:divide-gray-800/50">
              {items.length === 0 ? (
                <tr><td colSpan={7} className="text-center py-12 text-gray-400">Aucune annulation</td></tr>
              ) : items.map(item => (
                <tr key={item.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                  <td className="px-4 py-3">{new Date(item.sessionDate).toLocaleDateString('fr-FR')}</td>
                  <td className="px-4 py-3">{item.teacher.user.firstName} {item.teacher.user.lastName}</td>
                  <td className="px-4 py-3">{item.timetableSlot?.subject?.name ?? '-'} / {item.timetableSlot?.class?.name ?? '-'}</td>
                  <td className="px-4 py-3 max-w-xs truncate">{item.reason}</td>
                  <td className="px-4 py-3"><span className={`badge ${STATUS_BADGE[item.status]}`}>{STATUS_LABEL[item.status]}</span></td>
                  <td className="px-4 py-3 text-gray-500">{item.rescheduledDate ? new Date(item.rescheduledDate).toLocaleDateString('fr-FR') : '-'}</td>
                  <td className="px-4 py-3">
                    {canValidate && item.status === 'PENDING' && (
                      <button onClick={() => setShowValidateModal(item.id)} className="btn-secondary py-1 px-2 text-xs">
                        Décider
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Request modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="card w-full max-w-md p-6">
            <h2 className="text-lg font-semibold mb-4">Demande d'annulation</h2>
            <form onSubmit={handleSubmit(request)} className="space-y-3">
              <div>
                <label className="label">Créneau concerné</label>
                <select className="input" {...register('timetableSlotId', { required: true })}>
                  <option value="">Choisir...</option>
                  {slots.map(s => (
                    <option key={s.id} value={s.id}>{s.subject.name} - {s.class.name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Date du cours annulé</label>
                <input type="date" className="input" {...register('sessionDate', { required: true })} />
              </div>
              <div>
                <label className="label">Motif</label>
                <textarea rows={3} className="input resize-none" {...register('reason', { required: true })} placeholder="Expliquez le motif de l'annulation..." />
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1 justify-center">Envoyer</button>
                <button type="button" onClick={() => { setShowModal(false); reset(); }} className="btn-secondary flex-1 justify-center">Annuler</button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Validate modal */}
      {showValidateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="card w-full max-w-md p-6">
            <h2 className="text-lg font-semibold mb-4">Décision sur l'annulation</h2>
            <form onSubmit={handleV(validate)} className="space-y-3">
              <div>
                <label className="label">Décision</label>
                <select className="input" {...regV('status', { required: true })}>
                  <option value="APPROVED">Approuver</option>
                  <option value="REJECTED">Rejeter</option>
                </select>
              </div>
              <div>
                <label className="label">Date de report (optionnel)</label>
                <input type="datetime-local" className="input" {...regV('rescheduledDate')} />
              </div>
              <div>
                <label className="label">Salle de report (optionnel)</label>
                <input className="input" {...regV('rescheduledRoom')} placeholder="Ex: Amphi B" />
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1 justify-center">Confirmer</button>
                <button type="button" onClick={() => { setShowValidateModal(null); resetV(); }} className="btn-secondary flex-1 justify-center">Fermer</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
