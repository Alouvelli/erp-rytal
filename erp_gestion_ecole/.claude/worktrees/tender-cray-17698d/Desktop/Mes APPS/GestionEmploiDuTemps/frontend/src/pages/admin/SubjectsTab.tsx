import { useEffect, useState } from 'react';
import { subjectApi } from '../../services/api';
import { Subject } from '../../types';
import { PlusIcon, TrashIcon } from '@heroicons/react/24/outline';
import { useForm } from 'react-hook-form';
import toast from 'react-hot-toast';

export default function SubjectsTab() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [showModal, setShowModal] = useState(false);
  const { register, handleSubmit, reset } = useForm();

  const load = () => subjectApi.getAll().then(({ data }) => setSubjects(data.data));
  useEffect(() => { load(); }, []);

  const create = async (data: any) => {
    try {
      await subjectApi.create({ ...data, coefficient: Number(data.coefficient), hoursPerWeek: Number(data.hoursPerWeek) });
      toast.success('Matière créée'); setShowModal(false); reset(); load();
    } catch { toast.error('Erreur'); }
  };

  const remove = async (id: string) => {
    if (!confirm('Supprimer cette matière ?')) return;
    await subjectApi.delete(id); toast.success('Matière supprimée'); load();
  };

  return (
    <div className="space-y-4">
      <button onClick={() => setShowModal(true)} className="btn-primary"><PlusIcon className="w-4 h-4" /> Nouvelle matière</button>
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800/50 border-b">
            <tr>
              {['Code', 'Nom', 'Coefficient', 'H/semaine', 'Actions'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50 dark:divide-gray-800/50">
            {subjects.map(s => (
              <tr key={s.id} className="hover:bg-gray-50 dark:hover:bg-gray-800/30">
                <td className="px-4 py-3"><span className="badge badge-blue">{s.code}</span></td>
                <td className="px-4 py-3 font-medium">{s.name}</td>
                <td className="px-4 py-3">{s.coefficient}</td>
                <td className="px-4 py-3">{s.hoursPerWeek ?? '-'}</td>
                <td className="px-4 py-3">
                  <button onClick={() => remove(s.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg"><TrashIcon className="w-4 h-4" /></button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="card w-full max-w-md p-6">
            <h2 className="text-lg font-semibold mb-4">Nouvelle matière</h2>
            <form onSubmit={handleSubmit(create)} className="space-y-3">
              <div><label className="label">Code</label><input className="input" {...register('code', { required: true })} placeholder="Ex: INF301" /></div>
              <div><label className="label">Nom</label><input className="input" {...register('name', { required: true })} placeholder="Ex: Développement Web" /></div>
              <div className="grid grid-cols-2 gap-3">
                <div><label className="label">Coefficient</label><input type="number" step="0.5" className="input" defaultValue={1} {...register('coefficient')} /></div>
                <div><label className="label">H/semaine</label><input type="number" step="0.5" className="input" {...register('hoursPerWeek')} /></div>
              </div>
              <div className="flex gap-3 pt-2">
                <button type="submit" className="btn-primary flex-1 justify-center">Créer</button>
                <button type="button" onClick={() => { setShowModal(false); reset(); }} className="btn-secondary flex-1 justify-center">Annuler</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
