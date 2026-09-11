import { useEffect, useState } from 'react';
import { roomApi } from '../../services/api';
import { Room } from '../../types';
import { PlusIcon, TrashIcon } from '@heroicons/react/24/outline';
import { useForm } from 'react-hook-form';
import toast from 'react-hot-toast';

export default function RoomsTab() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [showModal, setShowModal] = useState(false);
  const { register, handleSubmit, reset } = useForm();

  const load = () => roomApi.getAll().then(({ data }) => setRooms(data.data));
  useEffect(() => { load(); }, []);

  const create = async (data: any) => {
    try {
      await roomApi.create({ ...data, capacity: Number(data.capacity) });
      toast.success('Salle créée'); setShowModal(false); reset(); load();
    } catch { toast.error('Erreur'); }
  };

  const remove = async (id: string) => {
    if (!confirm('Supprimer cette salle ?')) return;
    await roomApi.delete(id); toast.success('Salle supprimée'); load();
  };

  return (
    <div className="space-y-4">
      <button onClick={() => setShowModal(true)} className="btn-primary"><PlusIcon className="w-4 h-4" /> Nouvelle salle</button>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {rooms.map(r => (
          <div key={r.id} className="card p-4 flex items-start justify-between">
            <div>
              <p className="font-semibold text-gray-900 dark:text-white">{r.name}</p>
              <p className="text-sm text-gray-500">{r.building}</p>
              <p className="text-xs text-gray-400 mt-1">{r.type} • {r.capacity} places</p>
            </div>
            <button onClick={() => remove(r.id)} className="p-1.5 text-red-500 hover:bg-red-50 rounded-lg shrink-0">
              <TrashIcon className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>

      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="card w-full max-w-md p-6">
            <h2 className="text-lg font-semibold mb-4">Nouvelle salle</h2>
            <form onSubmit={handleSubmit(create)} className="space-y-3">
              <div><label className="label">Nom</label><input className="input" {...register('name', { required: true })} placeholder="Ex: Amphi A" /></div>
              <div><label className="label">Bâtiment</label><input className="input" {...register('building')} placeholder="Ex: Bâtiment A" /></div>
              <div><label className="label">Type</label><input className="input" {...register('type')} placeholder="Ex: Amphithéâtre, Salle TD, Labo..." /></div>
              <div><label className="label">Capacité</label><input type="number" className="input" defaultValue={30} {...register('capacity')} /></div>
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
